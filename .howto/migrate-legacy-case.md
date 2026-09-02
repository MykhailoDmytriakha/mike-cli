when: outside mike's grammar and was never stamped · legacy case · legacy file(s) · TODO.md is not parsable · JOURNAL.md is not parsable · дело велось до mike · файлы без stamp · exit 3 на любой записи · mike migrate

# Перенести дело в старом формате под mike

Признак: `mike log` / `mike readme` / `mike todo` отвечают `exit 3 … outside mike's grammar and was never stamped`, `mike doctor` показывает `legacy —`, а `mike` на входе первой строкой `Order` называет legacy-файлы. Это дело писали до `mike` или руками. Записи в него не идут нарочно: пересборка по грамматике (S4) унесла бы содержимое в `.recover.md`.

```sh
mike migrate            # план: что куда, что остаётся на ревью — ничего не меняет
mike migrate --apply    # legacy/<дата-время>/ byte-for-byte, потом канонические файлы атомарно
mike                    # Order говорит, что переписать; State: mike readme set next "…"
```

Что переносится само: README — секции по имени (goal/context/summary → Context · decisions → Decisions · problems/risks/open → Problems · links → Links), остальные секции остаются в архиве и перечислены в плане; TODO — заголовки → фазы (English 1–3 слова, иначе `Legacy N`), чекбоксы → пункты (длиннее 80 — обрезаны, полный текст в архиве), пункты до первого заголовка → фаза `Legacy`, фаза со всеми сделанными пунктами закрыта (её файл помечен `migrated from legacy`, гейты reflect/align её пропускают); JOURNAL — не конвертируется: тип и 200 знаков угадать нельзя, новый журнал открывается одним PHASE со ссылкой на архив.

Что делать руками после `--apply`: прочитать `legacy/<дата-время>/README.md` и переписать `State`; перенести из старого журнала то, что ещё важно, — `mike log DECISION|PROBLEM|RESULT "…"`; пройти по строкам `review` из плана.

Частный случай: не в грамматике только TODO — `mike readme …` работает (без синхронизации `progress:`), `mike log` и `mike todo` ждут миграции. Только JOURNAL — то же самое. `mike check` на legacy-деле красный до миграции — это ожидаемо.
