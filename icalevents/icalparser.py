"""
Parse iCal data to Events.
"""
# for UID generation
from random import randint
from datetime import datetime, timedelta, date
from typing import Optional

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, rruleset, rrulestr
from dateutil.tz import UTC, gettz, tzlocal

from icalendar import Calendar, Alarm
from icalendar.prop import vDDDLists, vText


def now():
    """
    Get current time.

    :return: now as datetime with timezone
    """
    return datetime.now(UTC)


class Event:
    """
    Represents one event (occurrence in case of reoccurring events).
    """

    def __init__(self):
        """
        Create a new event occurrence.
        """
        self.uid = -1
        self.summary = None
        self.description = None
        self.start = None
        self.end = None
        self.all_day = True
        self.recurring = False
        self.location = None
        self.private = False
        self.created = None
        self.last_modified = None
        self.recurrence_id = None
        self.sequence = None
        self.status = None
        self.alarms = []

    def time_left(self, time=None):
        """
        timedelta form now to event.

        :return: timedelta from now
        """
        time = time or now()
        return self.start - time

    def __lt__(self, other):
        """
        Events are sorted by start time by default.

        :param other: other event
        :return: True if start of this event is smaller than other
        """
        if not other or not isinstance(other, Event):
            raise ValueError('Only events can be compared with each other! Other is %s' % type(other))
        else:
            return self.start < other.start

    def __str__(self):
        n = now()

        # compute time delta description
        if not self.all_day:
            if self.end > n > self.start:
                # event is now
                delta = "now"
            elif self.start > n:
                # event is a future event
                if self.time_left().days > 0:
                    delta = "%s days left" % self.time_left().days
                else:
                    hours = self.time_left().seconds / (60 * 60)
                    delta = "%.1f hours left" % hours
            else:
                # event is over
                delta = "ended"
        else:
            if self.end > n > self.start:
                delta = "today"
            elif self.start > n:
                delta = "%s days left" % self.time_left().days
            else:
                delta = "ended"

        return "%s: %s (%s)" % (self.start, self.summary, delta)

    def copy_to(self, new_start=None, uid=None):
        """
        Create a new event equal to this with new start date.

        :param new_start: new start date
        :param uid: UID of new event
        :return: new event
        """
        if not new_start:
            new_start = self.start

        if not uid:
            uid = "%s_%d" % (self.uid, randint(0, 1000000))

        ne = Event()
        ne.summary = self.summary
        ne.description = self.description
        ne.start = new_start
        
        if self.end:
            duration = self.end - self.start
            ne.end = (new_start + duration)

        ne.all_day = self.all_day
        ne.recurring = self.recurring
        ne.location = self.location
        ne.private = self.private
        ne.uid = uid
        ne.created = self.created
        ne.last_modified = self.last_modified
        
        ne.alarms = self.alarms


        return ne


def encode(value: Optional[vText]) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(value)
    except UnicodeEncodeError:
        return str(value.encode('utf-8'))


def create_event(component, tz=UTC):
    """
    Create an event from its iCal representation.

    :param component: iCal component
    :param tz: timezone for start and end times
    :return: event
    """

    event = Event()

    event.start = normalize(component.get('dtstart').dt, tz=tz)

    if component.get('dtend'):
        event.end = normalize(component.get('dtend').dt, tz=tz)
    elif component.get('duration'): # compute implicit end as start + duration
        event.end = event.start + component.get('duration').dt
    else: # compute implicit end as start + 0
        event.end = event.start

    event.summary = encode(component.get('summary'))
    event.description = encode(component.get('description'))
    event.all_day = type(component.get('dtstart').dt) is date
    if component.get('rrule'):
        event.recurring = True
    event.location = encode(component.get('location'))

    if component.get('attendee'):
        event.attendee = component.get('attendee')
        if type(event.attendee) is list:
            temp = []
            for a in event.attendee:
                temp.append(a.encode('utf-8').decode('ascii'))
            event.attendee = temp
        else:
            event.attendee = event.attendee.encode('utf-8').decode('ascii')

    if component.get('X-APPLE-EWS-BUSYSTATUS'):
        event.status=component.get('X-APPLE-EWS-BUSYSTATUS')

    if component.get('uid'):
        event.uid = component.get('uid').encode('utf-8').decode('ascii')

    if component.get('organizer'):
        event.organizer = component.get('organizer').encode('utf-8').decode('ascii')

    if component.get('class'):
        event_class = component.get('class')
        event.private = event_class == 'PRIVATE' or event_class == 'CONFIDENTIAL'

    if component.get('recurrence-id'):
        event.recurrence_id = component.get('recurrence-id').dt

    if component.get('sequence'):
        event.sequence = component.get('sequence')

    if component.get('created'):
        event.created = normalize(component.get('created').dt, tz)

    if component.get('last-modified'):
        event.last_modified = normalize(component.get('last-modified').dt, tz)
    elif event.created:
        event.last_modified = event.created

    for i, subcomponent in enumerate(component.subcomponents):
        if isinstance(subcomponent, Alarm):
            if subcomponent.get('trigger'):
                trigger = subcomponent.get('trigger')
                if isinstance(trigger.dt, datetime):
                    if trigger.dt < now():
                        # print(i, event.summary, trigger.dt)
                        # just ignore it -- a lot are 19760401T005545Z
                        continue
                    else:
                        raise NotImplementedError
                elif isinstance(trigger.dt, timedelta):
                    event.alarms.append(trigger.dt)

    return event


def normalize(dt, tz=UTC):
    """
    Convert date or datetime to datetime with timezone.

    :param dt: date to normalize
    :param tz: the normalized date's timezone
    :return: date as datetime with timezone
    """
    if type(dt) is date:
        dt = dt + relativedelta(hour=0)
    elif type(dt) is datetime:
        pass
    else:
        raise ValueError("unknown type %s" % type(dt))

    if dt.tzinfo:
        dt = dt.astimezone(tz)
    else:
        dt = dt.replace(tzinfo=tz)

    return dt


def parse_events(content, start=None, end=None, default_span=timedelta(days=7)):
    """
    Query the events occurring in a given time range.

    :param content: iCal URL/file content as String
    :param start: start date for search, default today
    :param end: end date for search
    :param default_span: default query length (one week)
    :return: events as list
    """
    if not start:
        start = now()

    if not end:
        end = start + default_span

    if not content:
        raise ValueError('Content is invalid!')

    calendar = Calendar.from_ical(content)
    
    # Find the calendar's timezone info, or use UTC
    for c in calendar.walk():
        if c.name == 'VTIMEZONE':
            cal_tz = gettz(str(c['TZID']))
            break
    else:
        # cal_tz = UTC
        cal_tz = tzlocal()

    start = normalize(start, cal_tz)
    end = normalize(end, cal_tz)

    found = []
    for component in calendar.walk():
        if component.name == "VEVENT":
            e = create_event(component, cal_tz)
            # if "Lunch" == e.summary:
            #     print(e.summary, e.start, e.recurrence_id, (e.recurrence_id is not None and e.recurrence_id >= start- (e.end - e.start) and e.recurrence_id <= end))
            if e.recurring:
                # print("\n", e.summary)
                # Unfold recurring events according to their rrule
                rule = parse_rrule(component, cal_tz)
                dur = e.end - e.start
                # found.extend(e.copy_to(dt) for dt in rule.between(start - dur, end, inc=True))
                for dt in rule.between(start - dur, end, inc=True):
                    ecopy = e.copy_to(dt)
                    # print(ecopy.start.date(), [ e.date() for e in (rule._exdate if getattr(rule, "_exdate", []) else [])])
                    if ecopy.start.date() not in [ e.date() for e in (rule._exdate if getattr(rule, "_exdate", []) else [])]:
                        found.append(ecopy)
                # print(len(found), [str(e.start) for e in found], "exdates: ", [ str(e) for e in (rule._exdate if getattr(rule, "_exdate", []) else [])])

            elif (e.end >= start and e.start <= end) or (e.recurrence_id is not None and e.recurrence_id >= start-(e.end - e.start) and e.recurrence_id <= end):
                found.append(e)
    return found


def parse_rrule(component, tz=UTC):
    """
    Extract a dateutil.rrule object from an icalendar component. Also includes
    the component's dtstart and exdate properties. The rdate and exrule
    properties are not yet supported.
    
    :param component: icalendar component
    :param tz: timezone for DST handling
    :return: extracted rrule or rruleset
    """
    if component.get('rrule'):
        # component['rrule'] can be both a scalar and a list
        rrules = component['rrule']
        if not isinstance(rrules, list):
            rrules = [rrules]

        # Since DTSTART are always made timezone aware, UNTIL with no tzinfo
        # must be converted to UTC.
        for rule in rrules:
            until = rule.get("until")
            for idx, dt in enumerate(until or []):
                if not hasattr(dt, 'tzinfo'):
                    until[idx] = normalize(normalize(dt, tz=tz), tz=UTC)

        # Parse the rrules, might return a rruleset instance, instead of rrule
        rule = rrulestr('\n'.join(x.to_ical().decode() for x in rrules), dtstart=normalize(component['dtstart'].dt, tz=tz))
        
        if component.get('exdate'):
            # Make sure, to work with a rruleset
            if isinstance(rule, rrule):
                rules = rruleset()
                rules.rrule(rule)
                rule = rules
            
            # Add exdates to the rruleset
            for exd in extract_exdates(component):
                rule.exdate(exd)
        
        #TODO: What about rdates and exrules?
        
    # You really want an rrule for a component without rrule? Here you are.
    else:
        rule = rruleset()
        rule.rdate(normalize(component['dtstart'].dt, tz=tz))
    
    return rule


def extract_exdates(component):
    """
    Compile a list of all exception dates stored with a component.
    
    :param component: icalendar iCal component
    :return: list of exception dates
    """
    dates = []

    exd_prop = component.get('exdate')
    if exd_prop:
        if isinstance(exd_prop, list): # In case there is more than one exdate property
            for exd_list in exd_prop:
                dates.extend(normalize(exd.dt) for exd in exd_list.dts)
        elif isinstance(exd_prop, vDDDLists):
            dates.extend(normalize(exd.dt) for exd in exd_prop.dts)

    return dates

