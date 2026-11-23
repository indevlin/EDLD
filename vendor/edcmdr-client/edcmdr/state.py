"""Per-commander state built from journal events, emitted as protocol categories."""
import json
import time
from datetime import datetime

from . import paths
from .config import SPEC

SHIP_NAMES: dict[str, str] = json.loads((paths.data_dir() / 'ships.json').read_text())
STAT_SECTIONS = set(SPEC['statistics_sections'])
RANK_KEYS = SPEC['rank_keys']
REP_KEYS = SPEC['reputation_keys']
MAX_SHIP_ID = 1_000_000

EVENTS = frozenset({
    'Commander', 'NewCommander', 'LoadGame', 'Shutdown', 'Rank', 'Progress', 'Promotion', 'Reputation',
    'Statistics', 'SquadronStartup', 'JoinedSquadron', 'LeftSquadron', 'KickedFromSquadron',
    'DisbandedSquadron', 'SquadronPromotion', 'SquadronDemotion', 'Powerplay', 'PowerplayJoin',
    'PowerplayLeave', 'PowerplayDefect', 'PowerplayRank', 'PowerplayMerits', 'EngineerProgress',
    'Location', 'FSDJump', 'CarrierJump', 'Docked', 'Undocked', 'SupercruiseEntry', 'ApproachBody', 'LeaveBody',
    'StoredShips', 'Loadout', 'ShipyardSwap', 'ShipyardNew', 'ShipyardSell', 'ShipyardTransfer',
    'SetUserShipName', 'SellShipOnRebuy',
})


def ship_name(t: str) -> str:
    t = (t or '').lower()
    return SHIP_NAMES.get(t) or t.replace('_', ' ').title()


def is_ship(t: str, sid) -> bool:
    return isinstance(sid, int) and 0 <= sid < MAX_SHIP_ID and bool(t) and not t.lower().endswith('_taxi')


class Commander:
    def __init__(self, fid: str):
        self.fid = fid
        self.name = ''
        self.mode = 'Unknown'
        self.in_game = False
        self.last_event = 0.0
        self.ranks = {'rank': {}, 'progress': {}, 'reputation': {}}
        self.statistics: dict = {}
        self.squadron: dict | None = None
        self.powerplay: dict | None = None
        self.engineers: dict[int, dict] = {}
        self.location = {'system': None, 'body': None, 'station': None, 'docked': False}
        self.ships: dict[int, dict] = {}
        self.current: int | None = None
        self.loaded = False

    # ── events ──────────────────────────────────────────────────────────────
    def handle(self, ev: dict) -> None:
        h = getattr(self, '_e_' + ev['event'], None)
        if h:
            h(ev)
        try:
            self.last_event = max(self.last_event, datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp())
        except (KeyError, TypeError, ValueError):
            pass

    def _e_Commander(self, ev):
        self.name = ev.get('Name') or self.name

    _e_NewCommander = _e_Commander

    def _e_LoadGame(self, ev):
        self.name = ev.get('Commander') or self.name
        mode = ev.get('GameMode')
        self.mode = mode if mode in ('Open', 'Solo', 'Group') else 'Unknown'
        self.in_game = True
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if is_ship(t, sid):
            s = self._ship(sid, t)
            s['name'] = ev.get('ShipName') or s['name']
            s['ident'] = ev.get('ShipIdent') or s['ident']
            self.current = sid

    def _e_Shutdown(self, ev):
        self.in_game = False

    def _e_Rank(self, ev):
        self.ranks['rank'].update({k: ev[k] for k in RANK_KEYS if isinstance(ev.get(k), int)})

    def _e_Progress(self, ev):
        self.ranks['progress'].update({k: ev[k] for k in RANK_KEYS if isinstance(ev.get(k), int)})

    def _e_Promotion(self, ev):
        for k in RANK_KEYS:
            if isinstance(ev.get(k), int):
                self.ranks['rank'][k] = ev[k]
                self.ranks['progress'][k] = 0

    def _e_Reputation(self, ev):
        self.ranks['reputation'].update({k: round(float(ev[k]), 2) for k in REP_KEYS
                                         if isinstance(ev.get(k), (int, float))})

    def _e_Statistics(self, ev):
        self.statistics = {k: {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float)) and vv >= 0}
                           for k, v in ev.items() if k in STAT_SECTIONS and isinstance(v, dict)}

    def _e_SquadronStartup(self, ev):
        self.squadron = {'id': ev.get('SquadronID'), 'name': ev.get('SquadronName'),
                         'rank': ev.get('CurrentRank'), 'rank_name': ev.get('CurrentRankName')}

    def _e_JoinedSquadron(self, ev):
        self.squadron = {'id': ev.get('SquadronID'), 'name': ev.get('SquadronName'), 'rank': None, 'rank_name': None}

    def _e_LeftSquadron(self, ev):
        self.squadron = None

    _e_KickedFromSquadron = _e_LeftSquadron
    _e_DisbandedSquadron = _e_LeftSquadron

    def _e_SquadronPromotion(self, ev):
        if self.squadron is not None:
            self.squadron['rank'] = ev.get('NewRank', self.squadron['rank'])
            self.squadron['rank_name'] = ev.get('NewRankName', self.squadron['rank_name'])

    _e_SquadronDemotion = _e_SquadronPromotion

    def _e_Powerplay(self, ev):
        self.powerplay = {'power': ev.get('Power'), 'rank': ev.get('Rank'), 'merits': ev.get('Merits')}

    def _e_PowerplayJoin(self, ev):
        self.powerplay = {'power': ev.get('Power'), 'rank': 1, 'merits': 0}

    def _e_PowerplayDefect(self, ev):
        self.powerplay = {'power': ev.get('ToPower'), 'rank': 1, 'merits': 0}

    def _e_PowerplayLeave(self, ev):
        self.powerplay = None

    def _e_PowerplayRank(self, ev):
        if self.powerplay is not None and isinstance(ev.get('Rank'), int):
            self.powerplay['rank'] = ev['Rank']

    def _e_PowerplayMerits(self, ev):
        if self.powerplay is not None and isinstance(ev.get('TotalMerits'), int):
            self.powerplay['merits'] = ev['TotalMerits']

    def _e_EngineerProgress(self, ev):
        items = ev.get('Engineers') if isinstance(ev.get('Engineers'), list) else [ev]
        for e in items:
            if isinstance(e, dict) and isinstance(e.get('EngineerID'), int) and e.get('Engineer'):
                prev = self.engineers.get(e['EngineerID'], {})
                self.engineers[e['EngineerID']] = {
                    'name': e['Engineer'], 'id': e['EngineerID'],
                    'state': e.get('Progress') or prev.get('state'),
                    'rank': e.get('Rank', prev.get('rank')),
                }

    def _e_Location(self, ev):
        self.location = {'system': ev.get('StarSystem'), 'body': ev.get('Body'),
                         'station': ev.get('StationName') if ev.get('Docked') else None,
                         'docked': bool(ev.get('Docked'))}

    _e_CarrierJump = _e_Location

    def _e_FSDJump(self, ev):
        self.location = {'system': ev.get('StarSystem'), 'body': None, 'station': None, 'docked': False}

    def _e_Docked(self, ev):
        self.location.update(station=ev.get('StationName'), docked=True, system=ev.get('StarSystem') or self.location['system'])
        if self.current in self.ships:
            self.ships[self.current].update(system=self.location['system'], station=ev.get('StationName'))

    def _e_Undocked(self, ev):
        self.location.update(station=None, docked=False)

    def _e_SupercruiseEntry(self, ev):
        self.location.update(body=None, station=None, docked=False)

    def _e_ApproachBody(self, ev):
        self.location['body'] = ev.get('Body')

    def _e_LeaveBody(self, ev):
        self.location['body'] = None

    def _ship(self, sid: int, t: str) -> dict:
        s = self.ships.setdefault(sid, {'id': sid, 'type': t.lower(), 'type_name': ship_name(t), 'name': None,
                                        'ident': None, 'value': None, 'hull': None, 'rebuy': None, 'jump': None,
                                        'cargo': None, 'system': None, 'station': None, 'modules': []})
        s['type'] = t.lower()
        s['type_name'] = ship_name(t)
        return s

    def _e_StoredShips(self, ev):
        seen = set()
        for s in ev.get('ShipsHere') or []:
            if is_ship(s.get('ShipType', ''), s.get('ShipID')):
                x = self._ship(s['ShipID'], s['ShipType'])
                x.update(name=s.get('Name') or x['name'], value=s.get('Value', x['value']),
                         system=ev.get('StarSystem'), station=ev.get('StationName'))
                seen.add(s['ShipID'])
        for s in ev.get('ShipsRemote') or []:
            if is_ship(s.get('ShipType', ''), s.get('ShipID')):
                x = self._ship(s['ShipID'], s['ShipType'])
                x.update(name=s.get('Name') or x['name'], value=s.get('Value', x['value']),
                         system=None if s.get('InTransit') else s.get('StarSystem'), station=None)
                seen.add(s['ShipID'])
        for sid in list(self.ships):
            if sid not in seen and sid != self.current:
                del self.ships[sid]

    def _e_Loadout(self, ev):
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if not is_ship(t, sid):
            return
        s = self._ship(sid, t)
        mods = []
        for m in ev.get('Modules') or []:
            if not isinstance(m, dict) or not m.get('Slot') or not m.get('Item'):
                continue
            e = m.get('Engineering')
            eng = None
            if isinstance(e, dict):
                eng = {'blueprint': e.get('BlueprintName'), 'level': e.get('Level'), 'quality': e.get('Quality'),
                       'experimental': e.get('ExperimentalEffect_Localised')}
            mods.append({'slot': m['Slot'], 'item': m['Item'], 'eng': eng})
        hv, mv = ev.get('HullValue'), ev.get('ModulesValue')
        s.update(name=ev.get('ShipName') or s['name'], ident=ev.get('ShipIdent') or s['ident'],
                 value=(hv or 0) + (mv or 0) if (hv or mv) else s['value'], hull=ev.get('HullHealth'),
                 rebuy=ev.get('Rebuy'), jump=ev.get('MaxJumpRange'), cargo=ev.get('CargoCapacity'), modules=mods)
        self.current = sid

    def _e_ShipyardSwap(self, ev):
        old = ev.get('StoreShipID')
        if old in self.ships:
            self.ships[old].update(system=self.location['system'], station=self.location['station'])
        sid, t = ev.get('ShipID'), ev.get('ShipType', '')
        if is_ship(t, sid):
            self._ship(sid, t)
            self.current = sid

    def _e_ShipyardNew(self, ev):
        sid, t = ev.get('NewShipID'), ev.get('ShipType', '')
        if is_ship(t, sid):
            self._ship(sid, t)
            self.current = sid

    def _e_ShipyardSell(self, ev):
        self.ships.pop(ev.get('SellShipID'), None)

    _e_SellShipOnRebuy = _e_ShipyardSell

    def _e_ShipyardTransfer(self, ev):
        if ev.get('ShipID') in self.ships:
            self.ships[ev['ShipID']].update(system=self.location['system'], station=self.location['station'])

    def _e_SetUserShipName(self, ev):
        sid, t = ev.get('ShipID'), ev.get('Ship', '')
        if is_ship(t, sid):
            s = self._ship(sid, t)
            s.update(name=ev.get('UserShipName') or s['name'], ident=ev.get('UserShipIdent') or s['ident'])

    # ── output ──────────────────────────────────────────────────────────────
    def categories(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.name:
            out['identity'] = {'name': self.name}
        if self.ranks['rank']:
            out['ranks'] = self.ranks
        if self.statistics:
            out['statistics'] = self.statistics
        if self.squadron is not None or self.loaded:
            out['squadron'] = self.squadron or {'id': None, 'name': None, 'rank': None, 'rank_name': None}
        if self.powerplay is not None:
            out['powerplay'] = self.powerplay
        if self.engineers:
            out['engineering'] = {'engineers': sorted(self.engineers.values(), key=lambda e: e['name'])}
        ships = sorted(self.ships.values(), key=lambda s: s['id'])
        if self.location['system']:
            out['location'] = dict(self.location, ships=[{'id': s['id'], 'system': s['system'], 'station': s['station']}
                                                         for s in ships if s['system'] or s['station']])
        if ships:
            out['fleet'] = {'current': self.current if self.current in self.ships else None,
                            'ships': [{k: v for k, v in s.items() if k not in ('system', 'station')} for s in ships]}
        return out

    def presence(self, stale_after: int = 900) -> dict:
        live = self.in_game and time.time() - self.last_event < stale_after
        cur = self.ships.get(self.current)
        return {'in_game': live, 'mode': self.mode if live else 'Unknown',
                'ship': cur['type_name'] if live and cur else None}
