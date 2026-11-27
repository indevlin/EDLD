"""Inara API events from journal events, one commander each.

Only events and properties in Inara's API documentation (https://inara.cz/elite/inara-api-docs/) are sent.
"""
import json
import os
from pathlib import Path

URL = 'https://inara.cz/inapi/v1/'

# The application key Inara issues for EDCMDR-client, for Inara's read-only requests; builds get it from the
# INARA_APP_KEY secret. Commander data is always sent under the player's own Inara API key.
try:
    from ._build_secret import INARA_APP_KEY  # type: ignore[attr-defined]
except ImportError:
    INARA_APP_KEY = os.environ.get('INARA_APP_KEY', '').strip()

RANKS = {'Combat': 'combat', 'Trade': 'trade', 'Explore': 'explore', 'Soldier': 'soldier',
         'Exobiologist': 'exobiologist', 'CQC': 'cqc', 'Federation': 'federation', 'Empire': 'empire'}
LOCKER = ('Items', 'Components', 'Data', 'Consumables')
SNAPSHOT = frozenset({'setCommanderCredits', 'setCommanderRankPilot', 'setCommanderRankPower', 'setCommanderGameStatistics',
                      'setCommanderReputationMajorFaction', 'setCommanderInventoryCargo', 'setCommanderInventoryMaterials',
                      'resetCommanderInventory', 'setCommanderInventory', 'setCommanderStorageModules'})


def throttled(status, text: str) -> bool:
    """Inara's "slow down": access revoked for an hour (status 400 with that text, or 429)."""
    t = (text or '').lower()
    return status == 429 or (status == 400 and ('too much requests' in t or 'temporarily revoked' in t))


def refused_key(status, text: str) -> bool:
    """The request refused for its API key or commander: held until the settings change."""
    t = (text or '').lower()
    return status == 400 and not throttled(status, text) and ('api key' in t or 'apikey' in t or 'commander' in t)


def _int(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _tier(v):
    try:
        return int(str(v).split()[-1])
    except (ValueError, IndexError):
        return None


def _read(journal_dir: Path | None, name: str):
    if journal_dir is None:
        return None
    try:
        return json.loads((journal_dir / f'{name}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


class Builder:
    """Tracks what Inara wants alongside events and turns events into Inara events."""

    def __init__(self):
        self.rank: dict[str, int] = {}
        self.progress: dict[str, float] = {}
        self.credits = self.wealth = self.loan = None
        self.ship_type = self.ship_id = None
        self.system = self.pos = self.station = None
        self.power = self.pp_rank = self.pp_merits = None
        self.last_loadout = None
        self.cg_seen: dict[int, tuple] = {}

    # ── state kept between events ──────────────────────────────────────────────────────────────

    def _figures(self, ev: dict) -> None:
        e = ev.get('event')
        if e == 'Rank':
            self.rank.update({RANKS[k]: int(ev[k]) for k in RANKS if isinstance(ev.get(k), int)})
        elif e == 'Progress':
            self.progress.update({RANKS[k]: ev[k] / 100.0 for k in RANKS if isinstance(ev.get(k), (int, float))})
        elif e == 'Promotion':
            for k in RANKS:
                if isinstance(ev.get(k), int):
                    self.rank[RANKS[k]], self.progress[RANKS[k]] = ev[k], 0.0
        elif e == 'LoadGame' and isinstance(ev.get('Credits'), int) and ev['Credits'] >= 0:
            self.credits, self.loan = ev['Credits'], _int(ev.get('Loan'))
        elif e == 'Statistics':
            w = (ev.get('Bank_Account') or {}).get('Current_Wealth')
            if isinstance(w, int) and w >= 0:
                self.wealth = w

    def track(self, ev: dict) -> None:
        self._figures(ev)
        e = ev.get('event')
        if e in ('LoadGame', 'Loadout'):
            self.ship_type = ev.get('Ship') or self.ship_type
            self.ship_id = ev.get('ShipID', self.ship_id)
        elif e == 'ShipyardSwap':
            self.ship_type, self.ship_id = ev.get('ShipType') or self.ship_type, ev.get('ShipID', self.ship_id)
        if e in ('FSDJump', 'CarrierJump', 'Location'):
            self.system = ev.get('StarSystem') or self.system
            self.pos = ev.get('StarPos') or self.pos
        if e in ('FSDJump', 'Undocked'):
            self.station = None
        if e == 'Docked' or (e in ('Location', 'CarrierJump') and ev.get('Docked')):
            self.station = ev.get('StationName')
            self.system = ev.get('StarSystem') or self.system
        if e == 'Powerplay':
            self.power, self.pp_rank, self.pp_merits = ev.get('Power'), ev.get('Rank'), ev.get('Merits')
        elif e in ('PowerplayJoin', 'PowerplayDefect'):
            self.power, self.pp_rank, self.pp_merits = ev.get('Power') or ev.get('ToPower'), 1, 0
        elif e == 'PowerplayLeave':
            self.power = None
        elif e == 'PowerplayRank':
            self.pp_rank = ev.get('Rank', self.pp_rank)
        elif e == 'PowerplayMerits':
            self.pp_merits = ev.get('TotalMerits', self.pp_merits)
        if e in ('ShipyardBuy', 'ShipyardSwap'):
            self.last_loadout = None

    def _ranks(self) -> list[dict]:
        out = []
        for k, v in self.rank.items():
            r = {'rankName': k, 'rankValue': v}
            if k in self.progress:
                r['rankProgress'] = round(self.progress[k], 4)
            out.append(r)
        return out

    def _ship(self, d: dict) -> dict:
        if self.ship_type:
            d['shipType'] = self.ship_type
        if self.ship_id is not None:
            d['shipGameID'] = self.ship_id
        return d

    def _here(self, d: dict) -> dict:
        if self.system:
            d['starsystemName'] = self.system
        return d

    def _credits(self) -> dict | None:
        if self.credits is None:
            return None
        d = {'commanderCredits': self.credits}
        if self.wealth is not None:
            d['commanderAssets'] = self.wealth
        if self.loan is not None:
            d['commanderLoan'] = self.loan
        return d

    # ── events ─────────────────────────────────────────────────────────────────────────────────

    def events(self, ev: dict, journal_dir: Path | None = None) -> list[tuple[str, dict | list]]:
        """(eventName, eventData) pairs for one journal event; journal_dir only for live events. Call track(ev) afterwards."""
        e = ev.get('event', '')
        self._figures(ev)
        handler = getattr(self, f'_e_{e}', None)
        out = list(handler(ev, journal_dir) or []) if handler else []
        if e == 'FSDJump' and self.rank:
            out.append(('setCommanderRankPilot', self._ranks()))
        return out

    def _e_LoadGame(self, ev, _d):
        out = [('setCommanderCredits', self._credits())] if self._credits() else []
        if self.rank:
            out.append(('setCommanderRankPilot', self._ranks()))
        return out

    def _e_Promotion(self, ev, _d):
        return [('setCommanderRankPilot', self._ranks())]

    def _e_Statistics(self, ev, _d):
        stats = {k: v for k, v in ev.items() if k not in ('timestamp', 'event') and isinstance(v, dict)}
        out = [('setCommanderGameStatistics', stats)] if stats else []
        if self._credits() and self.wealth is not None:
            out.append(('setCommanderCredits', self._credits()))
        return out

    def _e_Reputation(self, ev, _d):
        reps = [{'majorfactionName': k.lower(), 'majorfactionReputation': round(ev[k] / 100.0, 4)}
                for k in ('Federation', 'Empire', 'Alliance', 'Independent') if isinstance(ev.get(k), (int, float))]
        return [('setCommanderReputationMajorFaction', reps)] if reps else []

    def _e_EngineerProgress(self, ev, _d):
        eng = []
        for x in ev.get('Engineers') or [ev]:
            if isinstance(x, dict) and x.get('Engineer') and x.get('Progress'):
                d = {'engineerName': x['Engineer'], 'rankStage': x['Progress']}
                if isinstance(x.get('Rank'), int):
                    d['rankValue'] = x['Rank']
                eng.append(d)
        return [('setCommanderRankEngineer', eng)] if eng else []

    def _e_Powerplay(self, ev, _d):
        e = ev.get('event')
        joined = e in ('PowerplayJoin', 'PowerplayDefect')
        power = ev.get('Power') or ev.get('ToPower') or self.power
        if not power:
            return []
        d = {'powerName': power}
        rank = ev.get('Rank', 1 if joined else self.pp_rank)
        merits = ev.get('Merits', ev.get('TotalMerits', 0 if joined else self.pp_merits))
        if rank is not None:
            d['rankValue'] = int(rank)
        if merits is not None:
            d['meritsValue'] = int(merits)
        return [('setCommanderRankPower', d)]

    _e_PowerplayJoin = _e_PowerplayRank = _e_PowerplayMerits = _e_PowerplayDefect = _e_Powerplay

    def _e_PowerplayLeave(self, ev, _d):
        return [('setCommanderRankPower', {'powerName': self.power, 'rankValue': -1})] if self.power else []

    def _travel(self, name, ev, extra):
        if not ev.get('StarSystem'):
            return []
        d = {'starsystemName': ev['StarSystem']}
        if ev.get('StarPos'):
            d['starsystemCoords'] = ev['StarPos']
        d.update(extra)
        out = [(name, self._ship(d) if name != 'setCommanderTravelLocation' else d)]
        factions = [{'minorfactionName': f['Name'], 'minorfactionReputation': round(f['MyReputation'] / 100.0, 4)}
                    for f in ev.get('Factions') or []
                    if isinstance(f, dict) and f.get('Name') and isinstance(f.get('MyReputation'), (int, float))]
        if factions:
            out.append(('setCommanderReputationMinorFaction', factions))
        return out

    @staticmethod
    def _station(ev):
        d = {}
        if ev.get('StationName'):
            d['stationName'] = ev['StationName']
        if isinstance(ev.get('MarketID'), int):
            d['marketID'] = ev['MarketID']
        return d

    def _e_FSDJump(self, ev, _d):
        extra = {'jumpDistance': round(float(ev['JumpDist']), 2)} if isinstance(ev.get('JumpDist'), (int, float)) else {}
        if ev.get('Taxi'):
            extra['isTaxiShuttle'] = True
        return self._travel('addCommanderTravelFSDJump', ev, extra)

    def _e_CarrierJump(self, ev, _d):
        return self._travel('addCommanderTravelCarrierJump', ev, self._station(ev) if ev.get('Docked') else {})

    def _e_Location(self, ev, _d):
        extra = self._station(ev) if ev.get('Docked') else {}
        if ev.get('Body') and ev.get('BodyType') in ('Planet', 'Station') and 'Latitude' in ev:
            extra.update(starsystemBodyName=ev['Body'], starsystemBodyCoords=[ev['Latitude'], ev['Longitude']])
        return self._travel('setCommanderTravelLocation', ev, extra)

    def _e_Docked(self, ev, _d):
        d = {'starsystemName': ev.get('StarSystem', ''), **self._station(ev)}
        if self.pos:
            d['starsystemCoords'] = self.pos
        if ev.get('Taxi'):
            d['isTaxiShuttle'] = True
        return [('addCommanderTravelDock', self._ship(d))]

    def _e_Touchdown(self, ev, _d):
        system = ev.get('StarSystem') or self.system
        if not ev.get('PlayerControlled', True) or 'Latitude' not in ev or not system:
            return []
        d = {'starsystemName': system, 'starsystemBodyName': ev.get('Body', ''),
             'starsystemBodyCoords': [ev['Latitude'], ev['Longitude']], 'isTaxiShuttle': bool(ev.get('Taxi')),
             'isTaxiDropship': False}
        if self.pos:
            d['starsystemCoords'] = self.pos
        return [('addCommanderTravelLand', self._ship(d))]

    def _e_DropshipDeploy(self, ev, _d):
        if not ev.get('StarSystem'):
            return []
        return [('addCommanderTravelLand', {'starsystemName': ev['StarSystem'], 'starsystemBodyName': ev.get('Body', ''),
                                            'isTaxiShuttle': False, 'isTaxiDropship': True})]

    MISSION = (('Expiry', 'missionExpiry'), ('Influence', 'influenceGain'), ('Reputation', 'reputationGain'),
               ('Faction', 'minorfactionNameOrigin'), ('DestinationSystem', 'starsystemNameTarget'),
               ('DestinationStation', 'stationNameTarget'), ('TargetFaction', 'minorfactionNameTarget'),
               ('Commodity', 'commodityName'), ('Count', 'commodityCount'), ('Target', 'targetName'),
               ('TargetType', 'targetType'), ('KillCount', 'killCount'), ('PassengerType', 'passengerType'),
               ('PassengerCount', 'passengerCount'), ('PassengerVIPs', 'passengerIsVIP'),
               ('PassengerWanted', 'passengerIsWanted'))

    def _e_MissionAccepted(self, ev, _d):
        if not isinstance(ev.get('MissionID'), int):
            return []
        d = {'missionGameID': ev['MissionID'], 'missionName': ev.get('Name', '')}
        if self.system:
            d['starsystemNameOrigin'] = self.system
        if self.station:
            d['stationNameOrigin'] = self.station
        d.update({ik: ev[k] for k, ik in self.MISSION if ev.get(k) is not None})
        return [('addCommanderMission', d)]

    def _e_MissionCompleted(self, ev, _d):
        if not isinstance(ev.get('MissionID'), int):
            return []
        permits = [{'starsystemName': p} for p in ev.get('PermitsAwarded') or [] if isinstance(p, str)]
        d = {'missionGameID': ev['MissionID']}
        if _int(ev.get('Reward')) is not None:
            d['rewardCredits'] = _int(ev['Reward'])
        if _int(ev.get('Donated')) is not None:
            d['donationCredits'] = _int(ev['Donated'])
        if permits:
            d['rewardPermits'] = permits
        for k, ik in (('CommodityReward', 'rewardCommodities'), ('MaterialsReward', 'rewardMaterials')):
            items = [{'itemName': x.get('Name', ''), 'itemCount': int(x.get('Count', 0))}
                     for x in ev.get(k) or [] if isinstance(x, dict)]
            if items:
                d[ik] = items
        effects = []
        for f in ev.get('FactionEffects') or []:
            if not isinstance(f, dict) or not f.get('Faction'):
                continue
            fx = {'minorfactionName': f['Faction']}
            infl = [i.get('Influence') for i in f.get('Influence') or [] if isinstance(i, dict) and i.get('Influence')]
            if infl:
                fx['influenceGain'] = infl[0]
            if f.get('Reputation'):
                fx['reputationGain'] = f['Reputation']
            effects.append(fx)
        if effects:
            d['minorfactionEffects'] = effects
        return [('addCommanderPermit', p) for p in permits] + [('setCommanderMissionCompleted', d)]

    def _e_MissionFailed(self, ev, _d):
        return [('setCommanderMissionFailed', {'missionGameID': ev['MissionID']})] if isinstance(ev.get('MissionID'), int) else []

    def _e_MissionAbandoned(self, ev, _d):
        return [('setCommanderMissionAbandoned', {'missionGameID': ev['MissionID']})] if isinstance(ev.get('MissionID'), int) else []

    def _e_Died(self, ev, _d):
        killers = ev.get('Killers') if isinstance(ev.get('Killers'), list) else (
            [{'Name': ev['KillerName']}] if ev.get('KillerName') else [])
        names = [k['Name'] for k in killers if isinstance(k, dict) and k.get('Name')]
        d = self._here({})
        if len(names) == 1:
            d['opponentName'] = names[0]
        elif names:
            d['wingOpponentNames'] = names
        d['isPlayer'] = any(n.lower().startswith('cmdr ') for n in names)
        return [('addCommanderCombatDeath', d)]

    def _combat(self, name, ev, who, **flags):
        if not ev.get(who):
            return []
        return [(name, self._here({'opponentName': ev[who], 'isPlayer': bool(ev.get('IsPlayer')), **flags}))]

    def _e_Interdicted(self, ev, _d):
        return self._combat('addCommanderCombatInterdicted', ev, 'Interdictor', isSubmit=bool(ev.get('Submitted')))

    def _e_Interdiction(self, ev, _d):
        return self._combat('addCommanderCombatInterdiction', ev, 'Interdicted', isSuccess=bool(ev.get('Success')))

    def _e_EscapeInterdiction(self, ev, _d):
        return self._combat('addCommanderCombatInterdictionEscape', ev, 'Interdictor')

    def _e_PVPKill(self, ev, _d):
        return [('addCommanderCombatKill', self._here({'opponentName': ev['Victim']}))] if ev.get('Victim') else []

    def _e_Friends(self, ev, _d):
        name, st = ev.get('Name'), ev.get('Status')
        if not name:
            return []
        d = {'commanderName': name, 'gamePlatform': 'pc'}
        if st in ('Added', 'Online'):
            return [('addCommanderFriend', d)]
        if st in ('Declined', 'Lost'):
            return [('delCommanderFriend', d)]
        return []

    def _e_Materials(self, ev, _d):
        mats = [{'itemName': m.get('Name', ''), 'itemCount': int(m.get('Count', 0))}
                for key in ('Raw', 'Manufactured', 'Encoded') for m in ev.get(key) or [] if isinstance(m, dict)]
        return [('setCommanderInventoryMaterials', mats)] if mats else []

    def _e_Cargo(self, ev, d):
        if ev.get('Vessel', 'Ship') != 'Ship':
            return []
        inv = ev.get('Inventory')
        if inv is None:
            j = _read(d, 'Cargo')
            inv = j.get('Inventory') if isinstance(j, dict) and j.get('Vessel', 'Ship') == 'Ship' else None
        if not isinstance(inv, list):
            return []
        items = []
        for c in inv:
            if not isinstance(c, dict) or not c.get('Name'):
                continue
            x = {'itemName': c['Name'], 'itemCount': int(c.get('Count', 0))}
            if c.get('Stolen'):
                x['isStolen'] = True
            if isinstance(c.get('MissionID'), int):
                x['missionGameID'] = c['MissionID']
            items.append(x)
        return [('setCommanderInventoryCargo', items)]

    def _e_ShipLocker(self, ev, d):
        if not all(k in ev for k in LOCKER):
            ev = _read(d, 'ShipLocker') or {}
            if not all(k in ev for k in LOCKER):
                return []
        items = [{'itemName': x['Name'], 'itemCount': int(x.get('Count', 0)), 'itemType': t}
                 for t in LOCKER for x in ev.get(t) or [] if isinstance(x, dict) and x.get('Name')]
        return [('resetCommanderInventory', [{'itemType': t} for t in LOCKER]), ('setCommanderInventory', items)]

    def _e_StoredModules(self, ev, _d):
        items = []
        for m in ev.get('Items') or []:
            if not isinstance(m, dict) or not m.get('Name'):
                continue
            x = {'itemName': m['Name'], 'itemValue': int(m.get('BuyPrice', 0) or 0), 'isHot': bool(m.get('Hot'))}
            if m.get('StarSystem'):
                x['starsystemName'] = m['StarSystem']
            if isinstance(m.get('MarketID'), int):
                x['marketID'] = m['MarketID']
            if m.get('EngineerModifications'):
                x['engineering'] = {'blueprintName': m['EngineerModifications'], 'blueprintLevel': int(m.get('Level', 0)),
                                    'blueprintQuality': round(float(m.get('Quality', 0)), 2)}
            items.append(x)
        return [('setCommanderStorageModules', items)]

    @staticmethod
    def _sold(ev, id_key='SellShipID', type_key='SellOldShip'):
        if ev.get(type_key) and isinstance(ev.get(id_key), int):
            return [('delCommanderShip', {'shipType': ev[type_key], 'shipGameID': ev[id_key]})]
        return []

    def _e_ShipyardBuy(self, ev, _d):
        return self._sold(ev)

    def _e_ShipyardNew(self, ev, _d):
        if not ev.get('ShipType') or not isinstance(ev.get('NewShipID'), int):
            return []
        return [('addCommanderShip', {'shipType': ev['ShipType'], 'shipGameID': ev['NewShipID']})]

    def _e_ShipyardSwap(self, ev, _d):
        out = self._sold(ev)
        if ev.get('ShipType') and isinstance(ev.get('ShipID'), int):
            out.append(('setCommanderShip', {'shipType': ev['ShipType'], 'shipGameID': ev['ShipID'], 'isCurrentShip': True}))
        return out

    def _e_ShipyardSell(self, ev, _d):
        return self._sold(ev, 'SellShipID', 'ShipType')

    def _e_SellShipOnRebuy(self, ev, _d):
        return self._sold(ev, 'SellShipId', 'ShipType')

    def _e_ShipyardTransfer(self, ev, _d):
        if not ev.get('ShipType') or not isinstance(ev.get('ShipID'), int):
            return []
        d = self._here({'shipType': ev['ShipType'], 'shipGameID': ev['ShipID'],
                        'transferTime': int(ev.get('TransferTime', 0) or 0)})
        if self.station:
            d['stationName'] = self.station
        if isinstance(ev.get('MarketID'), int):
            d['marketID'] = ev['MarketID']
        return [('setCommanderShipTransfer', d)]

    def _e_StoredShips(self, ev, _d):
        out = []
        for here, key in ((True, 'ShipsHere'), (False, 'ShipsRemote')):
            for s in ev.get(key) or []:
                if not isinstance(s, dict) or not s.get('ShipType'):
                    continue
                d = {'shipType': s['ShipType'], 'isCurrentShip': False}
                if isinstance(s.get('ShipID'), int):
                    d['shipGameID'] = s['ShipID']
                if s.get('Name'):
                    d['shipName'] = s['Name']
                if s.get('Hot') is not None:
                    d['isHot'] = bool(s['Hot'])
                if here:
                    d.update(starsystemName=ev.get('StarSystem', ''), stationName=ev.get('StationName', ''))
                    if isinstance(ev.get('MarketID'), int):
                        d['marketID'] = ev['MarketID']
                elif s.get('StarSystem') and not s.get('InTransit'):
                    d['starsystemName'] = s['StarSystem']
                    if isinstance(s.get('ShipMarketID'), int):
                        d['marketID'] = s['ShipMarketID']
                out.append(('setCommanderShip', d))
        return out

    def _e_SetUserShipName(self, ev, _d):
        if not ev.get('Ship'):
            return []
        d = {'shipType': ev['Ship'], 'isCurrentShip': True}
        if isinstance(ev.get('ShipID'), int):
            d['shipGameID'] = ev['ShipID']
        if ev.get('UserShipName'):
            d['shipName'] = ev['UserShipName']
        if ev.get('UserShipId'):
            d['shipIdent'] = ev['UserShipId']
        return [('setCommanderShip', d)]

    def _e_Loadout(self, ev, _d):
        if not ev.get('Ship'):
            return []
        d = {'shipType': ev['Ship'], 'isCurrentShip': True}
        if isinstance(ev.get('ShipID'), int):
            d['shipGameID'] = ev['ShipID']
        for k, ik in (('ShipName', 'shipName'), ('ShipIdent', 'shipIdent')):
            if ev.get(k):
                d[ik] = ev[k]
        for k, ik in (('HullValue', 'shipHullValue'), ('ModulesValue', 'shipModulesValue'), ('Rebuy', 'shipRebuyCost'),
                      ('CargoCapacity', 'shipCargoCapacity')):
            if isinstance(ev.get(k), int):
                d[ik] = ev[k]
        if isinstance(ev.get('MaxJumpRange'), (int, float)):
            d['shipMaxJumpRange'] = round(float(ev['MaxJumpRange']), 2)
        if self.system:
            d['starsystemName'] = self.system
        if self.station:
            d['stationName'] = self.station
        out = [('setCommanderShip', d)]
        mods = [self._module(m) for m in ev.get('Modules') or [] if isinstance(m, dict) and m.get('Slot') and m.get('Item')]
        if mods:
            lo = {'shipType': ev['Ship'], 'shipLoadout': mods}
            if isinstance(ev.get('ShipID'), int):
                lo['shipGameID'] = ev['ShipID']
            if lo != self.last_loadout:
                self.last_loadout = lo
                out.append(('setCommanderShipLoadout', lo))
        return out

    @staticmethod
    def _module(m: dict) -> dict:
        x = {'slotName': m['Slot'], 'itemName': m['Item'], 'isOn': bool(m.get('On', True)),
             'itemPriority': int(m.get('Priority', 0)), 'itemHealth': round(float(m.get('Health', 1.0)), 4)}
        for k, ik in (('Value', 'itemValue'), ('AmmoInClip', 'itemAmmoClip'), ('AmmoInHopper', 'itemAmmoHopper')):
            if isinstance(m.get(k), int):
                x[ik] = m[k]
        if m.get('Hot') is not None:
            x['isHot'] = bool(m['Hot'])
        eng = m.get('Engineering')
        if isinstance(eng, dict) and eng.get('BlueprintName'):
            bp = {'blueprintName': eng['BlueprintName'], 'blueprintLevel': int(eng.get('Level', 0)),
                  'blueprintQuality': round(float(eng.get('Quality', 0)), 2), 'modifiers': []}
            if eng.get('ExperimentalEffect'):
                bp['experimentalEffect'] = eng['ExperimentalEffect']
            for mo in eng.get('Modifiers') or []:
                if not isinstance(mo, dict):
                    continue
                y = {'name': mo.get('Label', '')}
                if 'OriginalValue' in mo:
                    y.update(value=mo.get('Value'), originalValue=mo['OriginalValue'], lessIsGood=bool(mo.get('LessIsGood', 0)))
                elif 'ValueStr' in mo:
                    y['value'] = mo['ValueStr']
                elif 'Value' in mo:
                    y['value'] = mo['Value']
                bp['modifiers'].append(y)
            x['engineering'] = bp
        return x

    @staticmethod
    def _suit(ev) -> dict | None:
        if not isinstance(ev.get('LoadoutID'), int) or not isinstance(ev.get('SuitID'), int):
            return None
        mods = []
        for m in ev.get('Modules') or []:
            if not isinstance(m, dict) or not m.get('SlotName'):
                continue
            x = {'slotName': m['SlotName'], 'itemName': m.get('ModuleName', '')}
            if isinstance(m.get('Class'), int):
                x['itemClass'] = m['Class']
            if isinstance(m.get('SuitModuleID'), int):
                x['itemGameID'] = m['SuitModuleID']
            if m.get('WeaponMods'):
                x['engineering'] = [{'blueprintName': w} for w in m['WeaponMods']]
            mods.append(x)
        return {'loadoutGameID': ev['LoadoutID'], 'loadoutName': ev.get('LoadoutName', ''), 'suitGameID': ev['SuitID'],
                'suitType': ev.get('SuitName', ''), 'suitMods': list(ev.get('SuitMods') or []), 'suitLoadout': mods}

    def _e_SuitLoadout(self, ev, _d):
        s = self._suit(ev)
        return [('setCommanderSuitLoadout', s)] if s else []

    _e_CreateSuitLoadout = _e_SuitLoadout

    def _e_DeleteSuitLoadout(self, ev, _d):
        return [('delCommanderSuitLoadout', {'loadoutGameID': ev['LoadoutID']})] if isinstance(ev.get('LoadoutID'), int) else []

    def _e_RenameSuitLoadout(self, ev, _d):
        if not isinstance(ev.get('LoadoutID'), int):
            return []
        d = {'loadoutGameID': ev['LoadoutID'], 'loadoutName': ev.get('LoadoutName', '')}
        if ev.get('SuitName') and isinstance(ev.get('SuitID'), int):
            d.update(suitType=ev['SuitName'], suitGameID=ev['SuitID'])
        return [('updateCommanderSuitLoadout', d)]

    def _e_CommunityGoal(self, ev, _d):
        out = []
        for g in ev.get('CurrentGoals') or []:
            if not isinstance(g, dict) or not isinstance(g.get('CGID'), int):
                continue
            cgid, tier = g['CGID'], _tier(g.get('TierReached'))
            sig = (g.get('PlayerContribution'), tier, g.get('IsComplete'), g.get('CurrentTotal'), g.get('PlayerPercentileBand'))
            if self.cg_seen.get(cgid) == sig:
                continue
            self.cg_seen[cgid] = sig
            cg = {'communitygoalGameID': cgid, 'communitygoalName': g.get('Title', ''),
                  'starsystemName': g.get('SystemName', ''), 'stationName': g.get('MarketName', ''),
                  'isCompleted': bool(g.get('IsComplete')), 'contributorsNum': int(g.get('NumContributors', 0) or 0),
                  'contributionsTotal': int(g.get('CurrentTotal', 0) or 0)}
            if g.get('Expiry'):
                cg['goalExpiry'] = g['Expiry']
            if tier is not None:
                cg['tierReached'] = tier
            top = g.get('TopTier') if isinstance(g.get('TopTier'), dict) else {}
            if _tier(top.get('Name')) is not None:
                cg['tierMax'] = _tier(top['Name'])
            if top.get('Bonus'):
                cg['completionBonus'] = top['Bonus']
            if _int(g.get('TopRankSize')) is not None:
                cg['topRankSize'] = _int(g['TopRankSize'])
            p = {'communitygoalGameID': cgid, 'contribution': int(g.get('PlayerContribution', 0) or 0),
                 'percentileBand': int(g.get('PlayerPercentileBand', 0) or 0)}
            if _int(g.get('Bonus')) is not None:
                p['percentileBandReward'] = _int(g['Bonus'])
            if g.get('PlayerInTopRank') is not None:
                p['isTopRank'] = bool(g['PlayerInTopRank'])
            out += [('setCommunityGoal', cg), ('setCommanderCommunityGoalProgress', p)]
        return out
