"""Cross-chain PT inventory; independent of holdings, DB and alert snapshots.

Expiry is recomputed, not inherited from a cached active/expired flag. A recent
HTTP fetch is not an upstream quote timestamp. No liquidity number is labelled
an executable exit size, and no risk/family judgement is made here.
"""
from collections import Counter
from datetime import datetime, timezone
import math
import re
import time
from .client import PendleClient, PendleAPIError


class PTInventoryClient(PendleClient):
    def supported_chains(self):
        return self._get('/v1/chains')

    def all_assets(self):
        return self._get('/v1/assets/all')

    def all_markets_page(self,skip=0,limit=100):
        if isinstance(skip,bool) or not isinstance(skip,int) or skip<0:
            raise ValueError('skip must be a nonnegative integer')
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=100:
            raise ValueError('limit must be between 1 and 100')
        return self._get('/v2/markets/all',params={'skip':skip,'limit':limit})


def utc_now():
    return datetime.now(timezone.utc)


def expiry_utc(value):
    if isinstance(value,bool) or value is None:raise ValueError('Missing/invalid expiry')
    if isinstance(value,(int,float)) or (isinstance(value,str) and value.isdigit()):
        number=float(value)
        if not math.isfinite(number) or number<=0 or number>1e14:raise ValueError('Invalid expiry timestamp')
        result=datetime.fromtimestamp(number/1000 if number>1e11 else number,timezone.utc)
    else:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError('Expiry timezone missing')
    return result.astimezone(timezone.utc)


def contract(value):
    if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}',value):raise ValueError('Invalid contract address')
    return value.lower()


def finite_number(value):
    if value is None:return None
    if isinstance(value,bool):raise ValueError('Boolean is not a numeric quote')
    result=float(value)
    if not math.isfinite(result):raise ValueError('Non-finite quote')
    return result


class Limiter:
    def __init__(self):self.last=None
    def wait(self):
        if self.last is not None:
            remaining=1.05-(time.monotonic()-self.last)
            if remaining>0:time.sleep(remaining)
        self.last=time.monotonic()


def assets_by_id(payload):
    rows=payload.get('assets')
    if not isinstance(rows,list):raise ValueError('Asset directory unavailable')
    result={};conflicts=set()
    for item in rows:
        key=f"{int(item['chainId'])}-{contract(item['address'])}"
        if key in result and any(result[key].get(f)!=item.get(f) for f in ('decimals','symbol')):
            conflicts.add(key)
        result[key]=item
    return result,conflicts


def token_reference(value,market_chain,assets,conflicts,issues,role):
    if not isinstance(value,str):
        issues.append(role+'_reference_missing');return None
    try:
        cid,address=value.split('-',1);cid=int(cid);address=contract(address)
    except (ValueError,TypeError):
        issues.append(role+'_reference_invalid');return None
    key=f'{cid}-{address}'
    if cid!=market_chain and role in ('pt','yt','sy','underlying'):issues.append(role+'_chain_mismatch')
    info=assets.get(key)
    if info is None:issues.append(role+'_metadata_missing')
    if key in conflicts:issues.append(role+'_metadata_conflict')
    return {'asset_id':key,'chain_id':cid,'address':address,
            'symbol':(info or {}).get('symbol'),'name':(info or {}).get('name'),
            'decimals':(info or {}).get('decimals'),'tags':(info or {}).get('tags'),
            'display_symbol':(info or {}).get('proSymbol') or (info or {}).get('symbol'),
            'reference_kind':'Pendle accounting reference; may be scaled or virtual' if role=='accounting' else 'API asset reference; contract identity not risk-verified',
            'metadata_expiry':(info or {}).get('expiry')}


def normalize_market(source,assets,conflicts,fetched_at,now=None,detail=None,detail_fetched_at=None):
    now=now or utc_now();issues=[]
    cid=int(source['chainId']);address=contract(source['address'])
    if cid<=0:raise ValueError('Invalid market chain')
    local_assets=dict(assets)
    if detail is not None:
        if int(detail['chainId'])!=cid or contract(detail['address'])!=address:
            raise ValueError('Market detail identity mismatch')
        if expiry_utc(detail['expiry'])!=expiry_utc(source['expiry']):
            raise ValueError('Market detail expiry mismatch')
        for field in ('pt','yt','sy','underlyingAsset','accountingAsset'):
            info=detail.get(field)
            if isinstance(info,dict) and info.get('id'):
                key=info['id'].lower()
                if key!=f"{int(info['chainId'])}-{contract(info['address'])}":
                    raise ValueError('Asset metadata identity mismatch')
                if source.get(field,'').lower()!=key:raise ValueError('Directory/detail asset reference mismatch')
                local_assets[key]={**info,'tags':info.get('tags') or info.get('types')}
    try:
        expiry=expiry_utc(source.get('expiry'));days=(expiry-now).total_seconds()/86400
        maturity=expiry.isoformat();expired=days<=0
        state='expired' if expired else 'near_maturity' if days<7 else 'unexpired_ge_7d'
    except (ValueError,TypeError,OverflowError,OSError):
        maturity=None;days=None;expired=None;state='invalid_expiry';issues.append('expiry_invalid')
    tokens={role:token_reference(source.get(field),cid,local_assets,conflicts,issues,role)
            for role,field in [('pt','pt'),('yt','yt'),('sy','sy'),('underlying','underlyingAsset'),('accounting','accountingAsset')]}
    for role in ('pt','yt'):
        token=tokens[role]
        if token and token['tags'] is not None and role.upper() not in token['tags']:issues.append(role+'_role_mismatch')
        if token and token.get('metadata_expiry') and maturity:
            try:
                if expiry_utc(token['metadata_expiry'])!=expiry_utc(maturity):issues.append(role+'_expiry_mismatch')
            except (ValueError,TypeError,OverflowError,OSError):issues.append(role+'_metadata_expiry_invalid')
    details=detail if detail is not None else source.get('details') or {}
    upstream_stamp=(detail or {}).get('dataUpdatedAt')
    if upstream_stamp is None:
        upstream_age=None;freshness='fetch_time_only_upstream_timestamp_unavailable'
        if state!='expired':issues.append('upstream_quote_timestamp_missing')
    else:
        try:
            upstream_age=(now-expiry_utc(upstream_stamp)).total_seconds()/3600
            freshness='source_timestamp_current' if -5/60<=upstream_age<=24 else 'source_timestamp_stale_or_future'
            if freshness!='source_timestamp_current':issues.append('upstream_quote_stale_or_future')
        except (ValueError,TypeError,OverflowError,OSError):
            upstream_age=None;freshness='source_timestamp_invalid';issues.append('upstream_quote_timestamp_invalid')
    def quote(field,percent=False,nonnegative=False,usd=False,directory=False):
        try:
            value=(source.get('details') or {}).get(field) if directory else details.get(field)
            if usd and isinstance(value,dict):value=value.get('usd')
            value=finite_number(value)
            if value is not None and nonnegative and value<0:raise ValueError('Negative amount')
            return value*100 if value is not None and percent else value
        except (ValueError,TypeError,OverflowError):issues.append(field+'_invalid');return None
    implied=quote('impliedApy',percent=True)
    if implied is None:issues.append('pt_implied_apy_missing')
    return {'id':f'pendle_pt:{cid}:{address}','chain_id':cid,'market_address':address,
        'market_name':source.get('name'),'protocol':source.get('protocol'),
        'name':(tokens['pt'] or {}).get('symbol') or source.get('name'),
        'maturity':maturity,'days_to_maturity':days,'expired':expired,'maturity_state':state,
        'tokens':tokens,'pt_implied_apy_pct':implied,
        'source_underlying_apy_pct':quote('underlyingApy',percent=True),
        'source_pt_roi_fraction_unverified':quote('ptRoi'),
        'reported_liquidity_usd':quote('liquidity',nonnegative=True,usd=True),
        'reported_tvl_usd':quote('totalTvl',nonnegative=True,usd=True,directory=True),
        'reported_volume_usd':quote('tradingVolume',nonnegative=True,usd=True),
        'liquidity_basis':'API-reported market liquidity value; not validated executable entry/exit depth',
        'fetched_at':detail_fetched_at or fetched_at,'directory_fetched_at':fetched_at,'expiry_evaluated_at':now.isoformat(),
        'source_data_as_of':upstream_stamp,'source_age_hours_at_evaluation':upstream_age,
        'freshness_status':freshness,'freshness_basis':'market detail dataUpdatedAt; HTTP receipt separately recorded' if upstream_stamp else 'HTTP fetch time only; upstream quote-update timestamp unavailable',
        'source_market_active':(detail or {}).get('isActive'),
        'source_listing_flags':{k:(detail or {}).get(k) for k in ('isActive','isWhitelistedPro','isWhitelistedSimple','isWhitelistedLimitOrder')},
        'field_sources':{'pt_implied_apy_pct':'market_detail' if detail else 'directory',
                        'reported_liquidity_usd':'market_detail' if detail else 'directory',
                        'reported_tvl_usd':'directory; upstream update clock not provided'},
        'source_output_asset_ids':source.get('outputTokens'),
        'redemption_path_status':'Accounting reference is not a verified cash-redemption route; SY path/quotes remain to be checked',
        'source_row_timestamp':source.get('timestamp'),'source_row_timestamp_role':'Unclassified market metadata timestamp; not used as quote freshness',
        'source_categories':source.get('categoryIds'),'points_present':bool(source.get('points')),
        'quality_issues':sorted(set(issues)),'inventory_quality_ok':not issues,
        'risk_status':'not_screened','family_status':'accounting_asset_classification_pending'}


def legacy_audit(payload,now=None):
    now=now or utc_now();rows=[]
    for cid,group in payload.get('chains',{}).items():
        for address,row in group.get('markets',{}).items():
            try:
                days=(expiry_utc(row.get('maturity'))-now).total_seconds()/86400
                expired=days<=0
            except (ValueError,TypeError,OverflowError,OSError):days=None;expired=None
            rows.append({'chain_id':int(cid),'market_address':address,'actual_days_remaining':days,
                'cached_days_remaining':row.get('days_to_maturity'),'cached_expired':row.get('expired'),
                'actual_expired':expired,'expired_flag_disagrees':expired is not None and expired!=row.get('expired'),
                'per_market_timestamp_present':bool(row.get('fetched_at') or row.get('source_data_as_of'))})
    return {'generated_at':payload.get('generated_at'),'evaluated_at':now.isoformat(),'rows':rows,
        'summary':{'cached_rows':len(rows),'actual_unexpired_ge_7d':sum(r['actual_days_remaining'] is not None and r['actual_days_remaining']>=7 for r in rows),
        'expired_flag_conflicts':sum(r['expired_flag_disagrees'] for r in rows),
        'missing_per_market_timestamp':sum(not r['per_market_timestamp_present'] for r in rows)}}


def current_inventory(payload,now=None,min_days=7,max_age_hours=24):
    """Re-evaluate expiry and clocks on consumption, not cached status strings.

    This selects data-quality-ready records, not risk/liquidity/yield candidates.
    """
    now=now or utc_now();selected=[]
    for record in payload['markets']:
        try:
            days=(expiry_utc(record['maturity'])-now).total_seconds()/86400
            upstream_age=(now-expiry_utc(record['source_data_as_of'])).total_seconds()/3600
            fetch_age=(now-expiry_utc(record['fetched_at'])).total_seconds()/3600
        except (KeyError,TypeError,ValueError,OverflowError,OSError):continue
        if days<min_days or not -5/60<=upstream_age<=max_age_hours or not -5/60<=fetch_age<=max_age_hours:continue
        if not record['inventory_quality_ok']:continue
        selected.append({**record,'days_to_maturity':days,'expiry_evaluated_at':now.isoformat(),
                         'source_age_hours_at_evaluation':upstream_age})
    return {'schema_version':1,'evaluated_at':now.isoformat(),'source_generated_at':payload['generated_at'],
        'scope':'Quality-ready PT inventory; no risk, numeraire, liquidity or benchmark screen applied',
        'min_days':min_days,'max_age_hours':max_age_hours,'count':len(selected),
        'by_chain':dict(Counter(r['chain_id'] for r in selected)),'markets':selected}


def feed_projection(payload):
    result={k:v for k,v in payload.items() if not k.startswith('raw_')}
    if result.get('legacy_audit'):
        result['legacy_audit']={k:v for k,v in result['legacy_audit'].items() if k!='rows'}
    return result


def discover(client=None,limiter=None,now=None):
    client=client or PTInventoryClient();limiter=limiter or Limiter()
    started=utc_now().isoformat()
    limiter.wait();chains=client.supported_chains();chain_ids=chains.get('chainIds')
    if not isinstance(chain_ids,list) or not chain_ids:raise ValueError('Missing chain directory')
    limiter.wait();raw_assets=client.all_assets();assets,conflicts=assets_by_id(raw_assets)
    pages=[];rows=[];seen=set();total=None;skip=0
    while True:
        if skip>=100000:raise ValueError('Market pagination limit reached')
        limiter.wait();page=client.all_markets_page(skip=skip,limit=100);stamp=utc_now().isoformat()
        records=page.get('results',page.get('markets'));count=page.get('total')
        if not isinstance(records,list) or isinstance(count,bool) or not isinstance(count,int) or count<0:
            raise ValueError('Invalid market directory page')
        if total is not None and count!=total:raise ValueError('Market directory changed during pagination')
        total=count
        if page.get('skip')!=skip or page.get('limit')!=100:raise ValueError('Unexpected pagination envelope')
        pages.append({'fetched_at':stamp,'payload':page})
        for market in records:
            key=(int(market['chainId']),contract(market['address']))
            if key in seen:raise ValueError('Duplicate market across pages')
            seen.add(key);row=normalize_market(market,assets,conflicts,stamp,now=now)
            if row['chain_id'] not in chain_ids:
                row['quality_issues'].append('chain_not_in_current_chain_directory');row['inventory_quality_ok']=False
            rows.append(row)
        skip+=len(records)
        if skip>=total:
            if skip!=total:raise ValueError('Market count mismatch')
            break
        if not records:raise ValueError('Truncated market directory')
    if not rows:raise ValueError('Empty market directory')
    details=[];raw_lookup={(int(m['chainId']),contract(m['address'])):m for p in pages for m in p['payload'].get('results',p['payload'].get('markets',[]))}
    for index,row in enumerate(rows):
        if row['maturity_state'] in ('expired','invalid_expiry'):continue
        key=(row['chain_id'],row['market_address'])
        limiter.wait()
        try:
            detail=client.market_detail(*key);stamp=utc_now().isoformat()
            replacement=normalize_market(raw_lookup[key],assets,conflicts,row['fetched_at'],now=now,detail=detail,detail_fetched_at=stamp)
            if replacement['chain_id'] not in chain_ids:
                replacement['quality_issues'].append('chain_not_in_current_chain_directory');replacement['inventory_quality_ok']=False
            if detail.get('isActive') is not True:
                replacement['quality_issues'].append('market_not_confirmed_active');replacement['inventory_quality_ok']=False
            if detail.get('isWhitelistedPro') is False and detail.get('isWhitelistedSimple') is False:
                replacement['quality_issues'].append('not_listed_in_current_pendle_views');replacement['inventory_quality_ok']=False
            rows[index]=replacement;details.append({'fetched_at':stamp,'payload':detail})
        except (ValueError,KeyError,TypeError,PendleAPIError) as exc:
            row['quality_issues'].append('market_detail_unavailable_or_inconsistent');row['inventory_quality_ok']=False
            details.append({'chain_id':key[0],'market_address':key[1],'error_type':type(exc).__name__})
    evaluated=now or utc_now()
    for row in rows:
        if row['maturity']:
            days=(expiry_utc(row['maturity'])-evaluated).total_seconds()/86400
            row.update(days_to_maturity=days,expired=days<=0,maturity_state='expired' if days<=0 else 'near_maturity' if days<7 else 'unexpired_ge_7d')
        row['expiry_evaluated_at']=evaluated.isoformat()
    summary={'directory_markets':total,'reported_chain_ids':chain_ids,'observed_chain_ids':sorted({r['chain_id'] for r in rows}),
        'by_maturity_state':dict(Counter(r['maturity_state'] for r in rows)),
        'unexpired_ge_7d_by_chain':dict(Counter(r['chain_id'] for r in rows if r['maturity_state']=='unexpired_ge_7d')),
        'quality_issues':dict(Counter(i for r in rows for i in r['quality_issues'])),
        'quality_ok_unexpired_ge_7d':sum(r['inventory_quality_ok'] and r['maturity_state']=='unexpired_ge_7d' for r in rows),
        'missing_upstream_quote_timestamp':sum(r['source_data_as_of'] is None for r in rows),
        'unexpired_source_timestamp_current':sum(r['maturity_state']!='expired' and r['freshness_status']=='source_timestamp_current' for r in rows),
        'asset_metadata_conflicts':len(conflicts)}
    return {'schema_version':1,'collection_started_at':started,'generated_at':utc_now().isoformat(),
        'scope':'Official cross-chain directory including historical markets; inventory only, no risk-screened candidates',
        'sources':{'markets':client.base+'/v2/markets/all','assets':client.base+'/v1/assets/all','chains':client.base+'/v1/chains'},
        'summary':summary,'markets':rows,'raw_pages':pages,'raw_market_details':details,'raw_assets':raw_assets,'raw_chains':chains}
