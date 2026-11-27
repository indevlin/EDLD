"""EDDN messages from journal events, one commander each, on EDDN's published schemas."""
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

ENDPOINT = 'https://eddn.edcd.io:4430/upload/'

JOURNAL_DISALLOWED = frozenset({
    'ActiveFine', 'CockpitBreach', 'BoostUsed', 'FuelLevel', 'FuelUsed', 'JumpDist', 'Latitude', 'Longitude',
    'Wanted', 'IsNewEntry', 'NewTraitsDiscovered', 'Traits', 'VoucherAmount'})
FACTION_DISALLOWED = frozenset({'HappiestSystem', 'HomeSystem', 'MyReputation', 'SquadronFaction'})
MODULE_RE = re.compile(r'^Hpt_|^Int_|Armour_', re.IGNORECASE)
COMMODITY_RE = re.compile(r'^\$(.+)_name;$')
HORIZONS_SKU = 'ELITE_HORIZONS_V_PLANETARY_LANDINGS'
JOURNAL_EVENTS = frozenset({'Docked', 'FSDJump', 'Scan', 'Location', 'SAASignalsFound', 'CarrierJump'})
PLAIN = {'FSSAllBodiesFound': 'fssallbodiesfound', 'FSSBodySignals': 'fssbodysignals',
         'ScanBaryCentre': 'scanbarycentre', 'NavBeaconScan': 'navbeaconscan'}
JUMPS = ('FSDJump', 'Location', 'CarrierJump')


def schema(name: str, version: int) -> str:
    return f'https://eddn.edcd.io/schemas/{name}/{version}'


def unlocalised(d):
    if isinstance(d, dict):
        return {k: unlocalised(v) for k, v in d.items() if not k.endswith('_Localised') and not k.startswith('_')}
    if isinstance(d, list):
        return [unlocalised(x) for x in d]
    return d


def commodity(name: str) -> str:
    m = COMMODITY_RE.match(name)
    return m.group(1).lower() if m else name.lower()


def digest(d) -> str:
    return hashlib.md5(json.dumps(d, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Builder:
    """Tracks one commander's position and turns events into (schemaRef, message) pairs."""

    def __init__(self):
        self.system = self.address = self.pos = None
        self.prev = (None, None, None)
        self.horizons = self.odyssey = None
        self.docked_id = None
        self.docked_name = ''
        self.carrier_id = None
        self.fss: list[dict] = []
        self.seen: dict[str, str | None] = {}
        self.market_id = None

    # ── tracking ──────────────────────────────────────────────────────────────────────────────

    def track(self, ev: dict) -> None:
        e = ev.get('event')
        if e == 'LoadGame':
            if 'Horizons' in ev:
                self.horizons = bool(ev['Horizons'])
            if 'Odyssey' in ev:
                self.odyssey = bool(ev['Odyssey'])
        elif e == 'Docked':
            self.docked_id, self.docked_name = ev.get('MarketID'), ev.get('StationName') or ''
            for k in ('commodity', 'outfitting', 'shipyard', 'capi-commodity', 'capi-outfitting', 'capi-shipyard'):
                self.seen[k] = None
        elif e == 'Undocked':
            self.docked_id, self.docked_name = None, ''
        elif e == 'CarrierStats' and ev.get('CarrierType', 'FleetCarrier') == 'FleetCarrier':
            self.carrier_id = ev.get('CarrierID')
        if e in ('Location', 'CarrierJump'):
            docked = bool(ev.get('Docked'))
            self.docked_id = ev.get('MarketID') if docked else None
            self.docked_name = (ev.get('StationName') or '') if docked else ''
        if e in JUMPS:
            sa = ev.get('SystemAddress')
            if sa is not None and self.address is not None and sa != self.address:
                self.prev = (self.system, self.address, list(self.pos) if self.pos else None)
            if sa is not None:
                self.address = sa
            self.system = ev.get('StarSystem') or self.system
            if isinstance(ev.get('StarPos'), list) and len(ev['StarPos']) == 3:
                self.pos = list(ev['StarPos'])

    # ── building ──────────────────────────────────────────────────────────────────────────────

    def messages(self, ev: dict, journal_dir: Path | None) -> list[tuple[str, dict]]:
        """Messages for a live event. Call track(ev) afterwards."""
        e = ev.get('event', '')
        out = []
        if e != 'FSSSignalDiscovered' and self.fss:
            out += self._flush_fss(ev)
        if e in JOURNAL_EVENTS:
            out += self._journal(ev)
        elif e == 'FSSDiscoveryScan':
            out += self._located('fssdiscoveryscan', ev, drop=('Progress',))
        elif e == 'FSSSignalDiscovered':
            self.fss.append(ev)
        elif e in PLAIN:
            out += self._located(PLAIN[e], ev)
        elif e == 'CodexEntry':
            out += self._codex(ev)
        elif e == 'ApproachSettlement' and 'Latitude' in ev and 'Longitude' in ev:
            out += self._located('approachsettlement', ev)
        elif e in ('DockingGranted', 'DockingDenied'):
            out.append((schema(e.lower(), 1), self._flags(unlocalised(ev))))
        elif e == 'Market':
            out += self._market(ev, journal_dir)
        elif e == 'Outfitting':
            out += self._outfitting(ev, journal_dir)
        elif e == 'Shipyard':
            out += self._shipyard(ev, journal_dir)
        elif e == 'NavRoute':
            out += self._navroute(ev, journal_dir)
        elif e == 'FCMaterials':
            out += self._fcmaterials(journal_dir)
        elif e == 'MarketSell' and ev.get('IllegalGoods') is True:
            out += self._blackmarket(ev)
        elif e == 'CarrierTradeOrder':
            cid = ev.get('CarrierID')
            if cid and cid == self.carrier_id == self.docked_id:
                self.seen['commodity'] = None
                out += self._market({'MarketID': cid, 'timestamp': ev.get('timestamp', '')}, journal_dir)
        return out

    def _flags(self, msg: dict) -> dict:
        if self.horizons is not None:
            msg['horizons'] = self.horizons
        if self.odyssey is not None:
            msg['odyssey'] = self.odyssey
        return msg

    def _augment(self, msg: dict) -> bool:
        """Fill StarSystem, StarPos and SystemAddress from tracking; False when that would be wrong."""
        system, address, pos = self.system, self.address, self.pos
        sa = msg.get('SystemAddress')
        if sa is not None and sa != address:
            if sa == self.prev[1] and self.prev[2]:
                system, address, pos = self.prev
            else:
                return False
        if 'StarSystem' not in msg and msg.get('SystemName') is None and msg.get('System') is None:
            if not system:
                return False
            msg['StarSystem'] = system
        if 'StarPos' not in msg:
            if not pos:
                return False
            msg['StarPos'] = list(pos)
        if 'SystemAddress' not in msg:
            if address is None:
                return False
            msg['SystemAddress'] = address
        return True

    def _located(self, name: str, ev: dict, drop: tuple = ()) -> list:
        msg = unlocalised(deepcopy(ev))
        for k in drop:
            msg.pop(k, None)
        return [(schema(name, 1), self._flags(msg))] if self._augment(msg) else []

    def _journal(self, ev: dict) -> list:
        msg = unlocalised(deepcopy(ev))
        for k in JOURNAL_DISALLOWED:
            msg.pop(k, None)
        if isinstance(msg.get('Factions'), list):
            msg['Factions'] = [{k: v for k, v in f.items() if k not in FACTION_DISALLOWED}
                               for f in msg['Factions'] if isinstance(f, dict)]
        if ('StarPos' not in msg or 'StarSystem' not in msg) and not self._augment(msg):
            return []
        if 'SystemAddress' not in msg:
            return []
        return [(schema('journal', 1), self._flags(msg))]

    def _flush_fss(self, trigger: dict) -> list:
        sigs, self.fss = self.fss, []
        if trigger.get('event') in JUMPS:
            sa, system, pos = trigger.get('SystemAddress'), trigger.get('StarSystem'), trigger.get('StarPos')
        else:
            sa, system, pos = self.address, self.system, self.pos
        if sa is None or system is None or pos is None or sigs[0].get('SystemAddress') != sa:
            return []
        keep = []
        for s in sigs:
            if s.get('SystemAddress') != sa or s.get('USSType') == '$USS_Type_MissionTarget;':
                continue
            s2 = unlocalised(s)
            for k in ('event', 'horizons', 'odyssey', 'TimeRemaining', 'SystemAddress'):
                s2.pop(k, None)
            keep.append(s2)
        if not keep:
            return []
        msg = {'event': 'FSSSignalDiscovered', 'timestamp': sigs[0].get('timestamp', ''), 'SystemAddress': sa,
               'StarSystem': system, 'StarPos': list(pos), 'signals': keep}
        return [(schema('fsssignaldiscovered', 1), self._flags(msg))]

    def _codex(self, ev: dict) -> list:
        msg = unlocalised(deepcopy(ev))
        for k in ('IsNewEntry', 'NewTraitsDiscovered'):
            msg.pop(k, None)
        if self.address is None or msg.get('SystemAddress') != self.address:
            return []
        if 'StarPos' not in msg:
            if not self.pos:
                return []
            msg['StarPos'] = list(self.pos)
        if not msg.get('System') or not msg.get('EntryID'):
            return []
        return [(schema('codexentry', 1), self._flags(msg))]

    @staticmethod
    def _file(journal_dir: Path | None, name: str):
        if journal_dir is None:
            return None
        try:
            return json.loads((journal_dir / f'{name}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _once(self, kind: str, value) -> bool:
        """True when value differs from what was last sent for this kind."""
        h = digest(value)
        if self.seen.get(kind) == h:
            return False
        self.seen[kind] = h
        return True

    def _station(self, data: dict, trigger: dict) -> dict:
        return {'timestamp': data.get('timestamp', trigger.get('timestamp', '')),
                'systemName': data.get('StarSystem') or self.system or '',
                'stationName': data.get('StationName', ''), 'marketId': data.get('MarketID')}

    def _market(self, trigger: dict, journal_dir) -> list:
        data = self._file(journal_dir, 'Market')
        if not isinstance(data, dict) or data.get('MarketID') != trigger.get('MarketID'):
            return []
        try:
            goods = sorted(({'name': commodity(c['Name']), 'meanPrice': c['MeanPrice'], 'buyPrice': c['BuyPrice'],
                             'stock': c['Stock'], 'stockBracket': c['StockBracket'], 'sellPrice': c['SellPrice'],
                             'demand': c['Demand'], 'demandBracket': c['DemandBracket']}
                            for c in data.get('Items', [])
                            if 'nonmarketable' not in str(c.get('Category', '')).lower() and not c.get('legality')),
                           key=lambda x: x['name'])
        except (KeyError, TypeError):
            return []
        if data.get('MarketID') != self.market_id:
            self.market_id = data.get('MarketID')
            self.seen['outfitting'] = self.seen['shipyard'] = None
        if not self._once('commodity', [goods, data.get('MarketID'), data.get('StarSystem') or self.system]):
            return []
        msg = self._station(data, trigger)
        msg['commodities'] = goods
        if data.get('StationType'):
            msg['stationType'] = data['StationType']
        if data.get('CarrierDockingAccess'):
            msg['carrierDockingAccess'] = data['CarrierDockingAccess']
        return [(schema('commodity', 3), self._flags(msg))]

    def _outfitting(self, trigger: dict, journal_dir) -> list:
        data = self._file(journal_dir, 'Outfitting')
        if not isinstance(data, dict) or data.get('MarketID') != trigger.get('MarketID'):
            return []
        mods = sorted({MODULE_RE.sub(lambda m: m.group(0).capitalize(), i['Name'])
                       for i in data.get('Items', []) if isinstance(i, dict) and isinstance(i.get('Name'), str)
                       and MODULE_RE.search(i['Name']) and i['Name'].lower() != 'int_planetapproachsuite'
                       and (not i.get('sku') or i.get('sku') == HORIZONS_SKU)})
        if not mods or not self._once('outfitting', [mods, data.get('MarketID'), data.get('StarSystem') or self.system]):
            return []
        msg = self._station(data, trigger)
        msg['modules'] = mods
        return [(schema('outfitting', 2), self._flags(msg))]

    def _shipyard(self, trigger: dict, journal_dir) -> list:
        data = self._file(journal_dir, 'Shipyard')
        if not isinstance(data, dict) or data.get('MarketID') != trigger.get('MarketID'):
            return []
        ships = sorted({s['ShipType'] for s in data.get('PriceList') or [] if isinstance(s, dict) and s.get('ShipType')})
        if not ships or not self._once('shipyard', [ships, data.get('MarketID'), data.get('StarSystem') or self.system]):
            return []
        msg = self._station(data, trigger)
        msg['ships'] = ships
        return [(schema('shipyard', 2), self._flags(msg))]

    def capi(self, market, shipyard, mid, when: str) -> list[tuple[str, dict, str]]:
        """(schemaRef, message, gameversion) from CAPI /market and /shipyard, only while still docked at mid."""
        if mid is None or mid != self.docked_id:
            return []
        out = []
        st = {'timestamp': when, 'systemName': self.system or '', 'stationName': self.docked_name, 'marketId': mid}
        sy = shipyard if isinstance(shipyard, dict) and shipyard.get('id') == mid else {}
        mods = sy.get('modules') if isinstance(sy.get('modules'), dict) else {}
        ships = sy.get('ships') if isinstance(sy.get('ships'), dict) else {}
        listed = ships.get('shipyard_list') if isinstance(ships.get('shipyard_list'), dict) else {}
        gone = ships.get('unavailable_list') if isinstance(ships.get('unavailable_list'), list) else []
        mk = market if isinstance(market, dict) and market.get('id') == mid else {}
        econ = mk.get('economies') if isinstance(mk.get('economies'), dict) else {}
        horizons = (any(isinstance(e, dict) and e.get('name') == 'Colony' for e in econ.values())
                    or any(isinstance(m, dict) and m.get('sku') == HORIZONS_SKU for m in mods.values())
                    or any(isinstance(v, dict) and v.get('sku') == HORIZONS_SKU for v in listed.values()))
        flags = {'horizons': horizons}
        if self.odyssey is not None:
            flags['odyssey'] = self.odyssey
        if mk and isinstance(mk.get('commodities'), list) and self.system:
            try:
                goods = []
                for c in mk['commodities']:
                    if c.get('categoryname') == 'NonMarketable' or c.get('legality'):
                        continue
                    g = {'name': str(c['name']).lower(), 'meanPrice': int(c['meanPrice']), 'buyPrice': int(c['buyPrice']),
                         'stock': int(c['stock']), 'stockBracket': c['stockBracket'], 'sellPrice': int(c['sellPrice']),
                         'demand': int(c['demand']), 'demandBracket': c['demandBracket']}
                    if c.get('statusFlags'):
                        g['statusFlags'] = list(c['statusFlags'])
                    goods.append(g)
            except (KeyError, TypeError, ValueError):
                goods = None
            if goods is not None:
                goods.sort(key=lambda x: x['name'])
                if self._once('capi-commodity', [goods, mid, self.system]):
                    msg = {**st, 'commodities': goods, **flags}
                    if econ:
                        msg['economies'] = sorted(({'name': e['name'], 'proportion': e['proportion']} for e in econ.values()
                                                   if isinstance(e, dict) and 'name' in e and 'proportion' in e),
                                                  key=lambda e: e['name'])
                    if isinstance(mk.get('prohibited'), dict) and mk['prohibited']:
                        msg['prohibited'] = sorted(str(x) for x in mk['prohibited'].values())
                    out.append((schema('commodity', 3), msg, 'CAPI-Live-market'))
        if self.system:
            fit = sorted({MODULE_RE.sub(lambda m: m.group(0).capitalize(), str(m['name']).lower())
                          for m in mods.values() if isinstance(m, dict) and isinstance(m.get('name'), str)
                          and MODULE_RE.search(m['name']) and m.get('sku') in (None, HORIZONS_SKU)
                          and m['name'].lower() != 'int_planetapproachsuite'})
            if fit and self._once('capi-outfitting', [fit, mid, self.system, horizons]):
                out.append((schema('outfitting', 2), {**st, 'modules': fit, **flags}, 'CAPI-Live-shipyard'))
            hulls = sorted({str(v['name']).lower() for v in listed.values() if isinstance(v, dict) and v.get('name')}
                           | {str(v['name']).lower() for v in gone if isinstance(v, dict) and v.get('name')})
            if hulls and self._once('capi-shipyard', [hulls, mid, self.system, horizons]):
                out.append((schema('shipyard', 2), {**st, 'ships': hulls, **flags}, 'CAPI-Live-shipyard'))
        return out

    def _navroute(self, trigger: dict, journal_dir) -> list:
        data = self._file(journal_dir, 'NavRoute')
        route = data.get('Route') if isinstance(data, dict) else None
        if not route:
            return []
        hops = [{'StarSystem': h.get('StarSystem', ''), 'SystemAddress': h.get('SystemAddress', 0),
                 'StarPos': h.get('StarPos', [0, 0, 0]), 'StarClass': h.get('StarClass', '')}
                for h in route if isinstance(h, dict)]
        msg = {'timestamp': data.get('timestamp', trigger.get('timestamp', '')), 'event': 'NavRoute', 'Route': hops}
        return [(schema('navroute', 1), self._flags(msg))]

    def _fcmaterials(self, journal_dir) -> list:
        data = self._file(journal_dir, 'FCMaterials')
        if not isinstance(data, dict):
            return []
        for f in ('MarketID', 'CarrierName', 'CarrierID', 'Items'):
            if not data.get(f) and data.get(f) != 0:
                return []
        if not self._once('fcmaterials', [data['Items'], data.get('MarketID')]):
            return []
        return [(schema('fcmaterials_journal', 1), self._flags(unlocalised(deepcopy(data))))]

    def _blackmarket(self, ev: dict) -> list:
        name, price = commodity(ev.get('Type', '')), ev.get('SellPrice')
        if not name or not self.system or not self.docked_name or price is None:
            return []
        msg = {'timestamp': ev.get('timestamp', ''), 'systemName': self.system, 'stationName': self.docked_name,
               'name': name, 'sellPrice': int(price), 'prohibited': bool(ev.get('IllegalGoods', True))}
        if ev.get('MarketID') is not None:
            msg['marketId'] = ev['MarketID']
        return [(schema('blackmarket', 1), self._flags(msg))]
