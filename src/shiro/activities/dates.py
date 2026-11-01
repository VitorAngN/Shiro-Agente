"""Resolução determinística de prazos falados em pt-BR (ADR-0009).

O modelo só extrai a expressão ("pra sexta", "dia 12 às 19h"); este módulo a
converte em data e hora absolutas, com regras fixas e testadas por tabela:

* só o dia, sem horário: usa o horário padrão (23h59 para prazos);
* dia da semana: próxima ocorrência futura; com "que vem" ou "próxima", a da
  semana seguinte (semanas começam na segunda);
* "dia 12": este mês, ou o próximo se já passou;
* expressão vaga ou não reconhecida: devolve um problema para a SHIRO
  perguntar, em vez de chutar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from shiro.core.text import parse_number

WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
WEEKDAY_NAMES = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
MONTH_NAMES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

END_OF_DAY = time(23, 59)
_FILLERS = re.compile(r"^(?:pra|para|pro|ate|no|na|nos|em|de|do|da|o|a|lá|la|por volta de)\s+")
_PERIOD = r"(?:\s+(?P<period>da manha|da tarde|da noite|da madrugada))?"
_NOT_DURATION = r"(?!\s+(?:dias?|semanas?|mes|meses)\b)"
_SPECIAL_TIME = re.compile(r"(?:\b(?:as|a|ao)\s+)?\b(?P<special>meio dia|meia noite)\b")
_DIGIT_TIME = re.compile(
    r"(?:\b(?:as|a)\s+)?\b(?P<h>\d{1,2})" + _NOT_DURATION + r"(?:(?::|h)(?P<m>\d{2})|h|\s*horas?)?"
    r"(?P<half>\s+e\s+meia)?" + _PERIOD + r"(?=\s|$)"
)
_WORD_TIME = re.compile(
    r"\b(?:as|a)\s+(?P<words>[a-z]+(?:\s+e\s+(?!meia\b)[a-z]+)?)"
    + _NOT_DURATION
    + r"(?:\s+horas?)?"
    r"(?P<half>\s+e\s+meia)?" + _PERIOD + r"(?=\s|$)"
)
_BARE_WORD_TIME = re.compile(
    r"\b(?P<words>[a-z]+)(?P<half>\s+e\s+meia)?"
    r"\s+(?P<period>da manha|da tarde|da noite|da madrugada)\b"
)
_WEEKDAY = re.compile(
    r"^(?:(?P<next1>proxima|proximo)\s+)?(?P<day>segunda|terca|quarta|quinta|sexta|sabado|domingo)"
    r"(?:\s+feira)?(?:\s+(?P<next2>que vem|da semana que vem|da proxima semana))?$"
)
_DAY_OF_MONTH = re.compile(
    r"^(?:(?P<dia>dia)\s+)?(?P<day>\d{1,2}|[a-z]+(?:\s+e\s+[a-z]+)?)"
    r"(?:\s+de\s+(?P<month>" + "|".join(MONTHS) + r"))?"
    r"(?:\s+(?:do\s+)?(?P<next>mes que vem|proximo mes))?$"
)
_NUMERIC_DATE = re.compile(r"^(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2}|\d{4}))?$")
_RELATIVE = re.compile(
    r"^(?:(?:daqui a|daqui|em|dentro de)\s+)?(?P<n>[a-z0-9]+)\s+(?P<unit>dias?|semanas?)$"
)
_NEXT_WEEK = re.compile(r"^(?:a\s+)?(?:semana que vem|proxima semana)$")
_NEXT_MONTH = re.compile(r"^(?:o\s+)?(?:mes que vem|proximo mes)$")


@dataclass(frozen=True)
class Resolution:
    when: datetime | None
    problem: str | None = None
    has_time: bool = False

    @property
    def ok(self) -> bool:
        return self.problem is None


def _clean(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    plain = re.sub(r"[^a-z0-9/: ]", " ", plain.replace("-", " "))
    return re.sub(r"\s+", " ", plain).strip()


def _strip_fillers(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, _FILLERS.sub("", text).strip()
    return text


def _apply_period(hour: int, period: str | None) -> int:
    if period in ("da tarde", "da noite") and hour < 12:
        return hour + 12
    if period in ("da manha", "da madrugada") and hour == 12:
        return 0
    return hour


def _extract_time(text: str) -> tuple[time | None, str, str | None]:
    """(horário, texto sem o horário, problema)."""
    if match := _SPECIAL_TIME.search(text):
        found = time(12, 0) if match["special"] == "meio dia" else END_OF_DAY
        return found, (text[: match.start()] + text[match.end() :]).strip(), None
    for pattern in (_DIGIT_TIME, _WORD_TIME, _BARE_WORD_TIME):
        for match in pattern.finditer(text):
            groups = match.groupdict()
            if pattern is _DIGIT_TIME:
                # "dia 12" ou "12/11" não são horário; exige um marcador de hora.
                marked = (
                    groups["m"] is not None
                    or "h" in match.group(0)[len(groups["h"]) :]
                    or match.group(0).startswith(("as ", "a "))
                    or groups["period"] is not None
                    or "hora" in match.group(0)
                )
                if not marked or re.search(r"\bdia\s+$", text[: match.start()]):
                    continue
                hour: int | None = int(groups["h"])
            else:
                hour = parse_number(groups["words"])
                if hour is None:
                    continue
            minute = int(groups.get("m") or 0) if pattern is _DIGIT_TIME else 0
            if groups.get("half"):
                minute = 30
            hour = _apply_period(hour, groups.get("period"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None, text, "Esse horário não existe."
            rest = (text[: match.start()] + text[match.end() :]).strip()
            return time(hour, minute), rest, None
    return None, text, None


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    for candidate in range(day.day, 27, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    return date(year, month, min(day.day, 28))


def _resolve_date(text: str, today: date, base: datetime | None) -> date | str | None:
    """Data, mensagem de problema, ou ``None`` se não há parte de data."""
    if not text:
        return None
    if text == "hoje":
        return today
    if text == "amanha":
        return today + timedelta(days=1)
    if text == "depois de amanha":
        return today + timedelta(days=2)
    if match := _WEEKDAY.match(text):
        weekday = WEEKDAYS[match["day"]]
        if match["next1"] or match["next2"]:
            next_monday = today + timedelta(days=7 - today.weekday())
            return next_monday + timedelta(days=weekday)
        return today + timedelta(days=(weekday - today.weekday()) % 7)
    if match := _RELATIVE.match(text):
        amount = parse_number(match["n"])
        if amount is not None and amount > 0:
            days = amount * (7 if match["unit"].startswith("semana") else 1)
            return today + timedelta(days=days)
    if _NEXT_WEEK.match(text):
        if base is not None:
            return base.date() + timedelta(days=7)
        return "Qual dia da semana que vem?"
    if _NEXT_MONTH.match(text):
        if base is not None:
            return _add_months(base.date(), 1)
        return "Qual dia do mês que vem?"
    if match := _NUMERIC_DATE.match(text):
        day, month = int(match["d"]), int(match["m"])
        year = int(match["y"]) if match["y"] else today.year
        year += 2000 if year < 100 else 0
        try:
            found = date(year, month, day)
        except ValueError:
            return f"A data {day}/{month} não existe."
        if not match["y"] and found < today:
            found = found.replace(year=year + 1)
        return found
    if match := _DAY_OF_MONTH.match(text):
        day_number = parse_number(match["day"])
        explicit = match["dia"] or match["month"] or match["next"]
        if day_number is None or not explicit or not 1 <= day_number <= 31:
            return None if not explicit else "Não entendi o dia."
        if match["month"]:
            month = MONTHS[match["month"]]
            for year in (today.year, today.year + 1):
                try:
                    found = date(year, month, day_number)
                except ValueError:
                    return f"{MONTH_NAMES[month - 1].capitalize()} não tem dia {day_number}."
                if found >= today:
                    return found
            return f"Não entendi o dia {day_number}."
        start = 1 if match["next"] else 0
        for offset in range(start, start + 3):
            first = _add_months(today.replace(day=1), offset)
            try:
                found = first.replace(day=day_number)
            except ValueError:
                continue
            if found >= today:
                return found
        return f"Não existe dia {day_number} nos próximos meses."
    return None


def resolve(
    text: str | None,
    *,
    now: datetime,
    default_time: time = END_OF_DAY,
    base: datetime | None = None,
) -> Resolution:
    """Converte a expressão falada em data e hora absolutas, no fuso de ``now``.

    Args:
        text: a expressão como o usuário falou; vazia significa "sem prazo".
        now: agora, com fuso.
        default_time: horário usado quando só o dia é informado.
        base: prazo atual, para expressões relativas ao adiar ("semana que vem").
    """
    cleaned = _strip_fillers(_clean(text or ""))
    if not cleaned:
        return Resolution(when=None)
    found_time, rest, problem = _extract_time(cleaned)
    if problem:
        return Resolution(when=None, problem=problem)
    rest = _strip_fillers(rest)
    today = now.date()
    found_date = _resolve_date(rest, today, base)
    if isinstance(found_date, str):
        return Resolution(when=None, problem=found_date)
    if found_date is None:
        if rest:
            return Resolution(
                when=None,
                problem=(
                    f'Não entendi o prazo "{(text or "").strip()}". '
                    'Pode dizer o dia, por exemplo "sexta" ou "dia 12"?'
                ),
            )
        if found_time is None:
            return Resolution(when=None)
        when = datetime.combine(today, found_time, tzinfo=now.tzinfo)
        if when <= now:
            when += timedelta(days=1)
        return Resolution(when=when, has_time=True)
    # Ao adiar sem dizer horário, mantém o horário do prazo atual.
    fallback = base.astimezone(now.tzinfo).time() if base is not None else default_time
    when = datetime.combine(found_date, found_time or fallback, tzinfo=now.tzinfo)
    if when <= now:
        if _WEEKDAY.match(rest) and found_date == today:
            return Resolution(when=when + timedelta(days=7), has_time=found_time is not None)
        return Resolution(when=None, problem="Esse horário já passou.")
    return Resolution(when=when, has_time=found_time is not None)


def describe(when: datetime, now: datetime) -> str:
    """Data por extenso para a SHIRO repetir: "sexta-feira, 6 de novembro, às 23h59"."""
    today = now.date()
    day = when.date()
    hour = f"{when.hour}h{when.minute:02d}" if when.minute else f"{when.hour}h"
    if day == today:
        prefix = "hoje"
    elif day == today + timedelta(days=1):
        prefix = "amanhã"
    else:
        prefix = f"{WEEKDAY_NAMES[day.weekday()]}, {day.day} de {MONTH_NAMES[day.month - 1]}"
        if day.year != today.year:
            prefix += f" de {day.year}"
    return f"{prefix}, às {hour}"
