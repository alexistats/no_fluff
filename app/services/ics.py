"""Building the per-user iCalendar feed — hand-assembled RFC 5545 text.

Kept dependency-free on purpose: the feed is a handful of all-day VEVENTs.
Calendar apps (Google Calendar, Cozi, Apple Calendar) subscribe to the URL
and refresh on their own cadence.
"""

from datetime import UTC, datetime, timedelta


def _escape(text):
    """Escape TEXT values per RFC 5545 (backslash first, then , ; and newlines)."""
    return (
        str(text)
        .replace('\\', '\\\\')
        .replace(';', '\\;')
        .replace(',', '\\,')
        .replace('\r\n', '\\n')
        .replace('\n', '\\n')
    )


def _folded(line):
    """RFC 5545 line folding: lines over 75 octets continue on a ' '-prefixed line."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return [line]
    lines = []
    prefix = b''
    while raw:
        limit = 75 - len(prefix)
        cut = min(limit, len(raw))
        # Never split inside a UTF-8 sequence (continuation bytes are 0b10xxxxxx).
        while cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        lines.append((prefix + raw[:cut]).decode('utf-8'))
        raw = raw[cut:]
        prefix = b' '
    return lines


def build_feed(schedules, labels, alarm_hour=7):
    """ICS text for a user's planned workouts.

    schedules: WorkoutSchedule rows; labels: {routine_type: display label}.
    Events are all-day; the VALARM fires at alarm_hour local time (honored by
    Apple Calendar — Google and Cozi ignore alarms on subscribed feeds, which
    is why email reminders exist as the reliable channel).
    """
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//NoFluff//workout schedule//EN',
        'CALSCALE:GREGORIAN',
        'X-WR-CALNAME:NoFluff workouts',
        'REFRESH-INTERVAL;VALUE=DURATION:PT1H',
        'X-PUBLISHED-TTL:PT1H',
    ]
    for entry in schedules:
        label = labels.get(entry.routine_type, entry.routine_type)
        start = entry.scheduled_date.strftime('%Y%m%d')
        end = (entry.scheduled_date + timedelta(days=1)).strftime('%Y%m%d')
        lines += [
            'BEGIN:VEVENT',
            f'UID:nofluff-sched-{entry.id}@nofluff',
            f'DTSTAMP:{stamp}',
            f'DTSTART;VALUE=DATE:{start}',
            f'DTEND;VALUE=DATE:{end}',
            f'SUMMARY:{_escape(f"Workout: {label}")}',
            'BEGIN:VALARM',
            'ACTION:DISPLAY',
            f'DESCRIPTION:{_escape(f"Workout today: {label}")}',
            f'TRIGGER;RELATED=START:PT{alarm_hour}H',
            'END:VALARM',
            'END:VEVENT',
        ]
    lines.append('END:VCALENDAR')

    out = []
    for line in lines:
        out.extend(_folded(line))
    return '\r\n'.join(out) + '\r\n'
