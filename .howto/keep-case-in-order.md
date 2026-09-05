when: Order говорит «State is behind» · «file(s) without summary» · «folder has no description» · «≈ … is verbatim in» · «limit 24» · README Links устарел · вход mike длинный · беспорядок в docs/

# Держать дело в порядке

Каждый `mike` заканчивается блоком `## Order` — по строке на то, что не на месте, с командой, которая это чинит. Пусто — `✓ everything in place`. То же в `mike order`; `mike check` печатает те же строки предупреждениями.

| строка Order | что сделать |
|---|---|
| `State is behind: N entries since as of …` | переписать «сейчас»: `mike readme set next "…"` или `mike readme --file README.md` — якорь `as of` встанет на свежую запись |
| `N file(s) without summary:` | вторая строка файла: `summary: одна фраза` — описания, уже написанные в Links, переносит `mike order --adopt` |
| `folder docs/ has no description` | `mike readme add links "docs/ — что здесь"` — строка папки твоя, файлы под ней mike допишет сам |
| `a.md ≈ b.md: NN % of a.md's text is verbatim in b.md` | назвать разницу в `summary:` обоих — или слить, если это копия. Считаются дословные фразы (тройки слов подряд), не словарь: два документа об одном предмете делят имена и даты и остаются двумя документами |
| `x.md is NN KB (limit 24)` | разделить по summary или сократить. Бюджета папки нет: счётчик байтов не отличает рабочие документы от воды |
| `overdue: N.M «…» was due …` | сделано → `mike todo done N.M`; сдвинулось → `mike todo due N.M <дата>`; больше не нужно → `mike todo cancel N.M "почему"` |
| `N broken link(s): file → target` | поправить ссылку руками или переносить файлы через `mike mv old new` — ссылки переписываются сами. В README/TODO мёртвая ссылка — нарушение `check` (F16), в документах — только эта строка |
| `State` держит строку, которая перестала быть правдой | `mike readme set <prefix> ""` или `mike readme drop state <prefix>` — строки `progress:`/`last:`/`as of:` держит mike, их не убрать |
| `N item(s) without a link to their material` | правило дела F17 включено (строка Context `rule: items link their material`): в текст пункта — `[имя](docs/файл.md)` через `mike todo edit N.M "…"`; не нужно в этом деле — убрать строку Context |
| `N.M is after N.K, which is gone` | зависимость снята или удалена: перевязать `mike todo after N.M "…"` (или `none`) — либо снять сам пункт `mike todo cancel N.M "почему"` |
| `nested case X: README unparsable` | ребёнок сломан и держит родителя открытым (F18): `mike --case X check`, починить через `mike migrate` или команды |
| `cannot close phase N: open items …` (отказ) | у каждого пункта два конца (F20): `mike todo done N.M "что вышло"` или `mike todo cancel N.M "почему"`; вся фаза не нужна — `mike phase cancel N "почему"` |
| `extra file in the case root` | унести в папку по виду (`docs/`, `research/`, `logs/`) |
| `pending X.recover.md` | внести строки командами mike, потом `rm` |

Почему так: предел на README один сдвигал воду этажом ниже — новый файл дёшев, слить два никто не делал. Теперь нижний слой виден сверху, а верх (Links, `last:`, `progress:`) рисуется из него и не гниёт.
