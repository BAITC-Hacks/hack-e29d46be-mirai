"""Small offline Russian query helpers; no implicit chat history."""
from __future__ import annotations

import re


def directions(question):
    q = str(question).lower().replace('ё', 'е')
    incoming = bool(re.search(r'входящ|от\s+кого|отправител|плательщик|поступлен|'
                              r'кто\b.*\b(?:перевод\w*|перевел\w*|отправ\w*|перечисл\w*|плат\w*)|'
                              r'откуда\b.*(?:деньг|перевод|поступ)', q))
    outgoing = bool(re.search(r'исходящ|\bкому\b|получател|'
                              r'\bкуда\b.*(?:перевод|отправ|ушл|уход|перечисл)|'
                              r'кто\b.*\bполуч\w*\b.*\bот\b', q))
    # A subject explicitly sends money, with no question about who sent to it.
    if not incoming and re.search(r'(?:узел|клиент|\bон\b|\bgid\b).*\b(?:перевод\w*|перевел\w*|отправ\w*|перечисл\w*)', q):
        outgoing = True
    return [name for name, matched in (('in', incoming), ('out', outgoing)) if matched]


def with_explicit_context(question, known_gids):
    text = str(question).strip()
    match = re.fullmatch(r'Контекст выбранного клиента:\s*gid\s+([0-9]{1,20})\.\s*\nВопрос:\s*(.*)',
                         text, re.IGNORECASE | re.DOTALL)
    if not match:
        return text
    context_gid, body = match.groups()
    # Explicit IDs in the actual question override the selection context.
    scrubbed = re.sub(r'кластер[а-я]*\s*#?\s*-?\d+|(?:топ|top|первые|первых|покажи)\s*\d{1,2}(?!\d)',
                      '', body.lower())
    explicit = re.search(r'(?:gid|уз(?:ел|ла|лу|лы|лов)|клиент[а-я]*)\s*[:#]?\s*[0-9]{1,20}(?!\d)', body, re.I)
    if explicit or any(gid in known_gids or len(gid) >= 6 for gid in re.findall(r'(?<!\d)[0-9]{1,20}(?!\d)', scrubbed)):
        return body
    # Global role/cluster/priority/limitation questions remain global even if UI
    # includes a selected client. Only node-specific wording uses that selection.
    local_reference = re.search(r'карточ|выбранн|\b(?:он|его|ему|нем|этот|этому)\b', body, re.I)
    global_query = re.search(r'кластер|приоритет|проверить|первым|ограничени|список|\b(?:топ|top)\b|'
                             r'консолид|сборщик|транзит|распределител|координатор|перифер|'
                             r'consolidator|transit|distributor|terminal|coordinator|peripheral', body, re.I)
    if global_query and not local_reference and not directions(body):
        return body
    if directions(body) or re.search(r'карточ|клиент|уз(?:ел|ла|лу)|связ|сосед|\b(?:он|его|ему|нем)\b', body, re.I):
        return body + '\ngid ' + context_gid
    return body
