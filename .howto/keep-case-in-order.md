when: Order говорит «State is behind» · «file(s) without summary» · «folder has no description» · «≈ … same words» · «limit 16 / 64 KB» · README Links устарел · вход mike длинный · беспорядок в docs/

# Держать дело в порядке

Каждый `mike` заканчивается блоком `## Order` — по строке на то, что не на месте, с командой, которая это чинит. Пусто — `✓ everything in place`. То же в `mike order`; `mike check` печатает те же строки предупреждениями.

| строка Order | что сделать |
|---|---|
| `State is behind: N entries since as of …` | переписать «сейчас»: `mike readme set next "…"` или `mike readme --file README.md` — якорь `as of` встанет на свежую запись |
| `N file(s) without summary:` | вторая строка файла: `summary: одна фраза` — описания, уже написанные в Links, переносит `mike order --adopt` |
| `folder docs/ has no description` | `mike readme add links "docs/ — что здесь"` — строка папки твоя, файлы под ней mike допишет сам |
| `a.md ≈ b.md (NN % same words)` | слить в один файл или назвать разницу в `summary:` обоих |
| `docs/ is NN KB (limit 64)` · `x.md is NN KB (limit 24)` | слить, удалить, разделить по summary — прежде чем добавлять новое |
| `extra file in the case root` | унести в папку по виду (`docs/`, `research/`, `logs/`) |
| `pending X.recover.md` | внести строки командами mike, потом `rm` |

Почему так: предел на README один сдвигал воду этажом ниже — новый файл дёшев, слить два никто не делал. Теперь нижний слой виден сверху, а верх (Links, `last:`, `progress:`) рисуется из него и не гниёт.
