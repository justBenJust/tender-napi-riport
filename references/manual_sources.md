# Kézi források és képernyőképek

Források: IDPR, EKR, TED, KEF, ARIBA, FLUENTA, UNIVERZAL (és bármely új, nagybetűs név). Adataik kézi CSV/XLSX-exportból, Wordbe tett képernyőképből, kérésre a kijelölt Outlook-forrásból ([útmutató](outlook_source.md)) vagy Claude in Chrome-ban a bejelentkezett portáloldalról ([útmutató](browser_source.md)) érkeznek; mind ugyanezt a JSON-sémát használja.

## Exportok

Egy export forrásonként, a tényleges oszlopok ellenőrzésével:

```text
python <skill>/scripts/tender_tools.py --days <N> --ted-api --source-file IDPR=<idpr.xlsx> --source-file EKR=<ekr.csv> --out <input.json>
```

A forrás nevét a fájlnévből, a dokumentum egyértelmű fejlécéből vagy a felhasználó megjelöléséből vedd, ne a beszerzés tárgyából; ha nem egyértelmű, kérdezd meg. Ismeretlen fejléchez készíts alias JSON-t (`--aliases`, lásd `column_aliases.example.json`). Kézi TED-exportot csak akkor adj meg, ha nincs `--ted-api` / `--ted-web-input` bemenet: a kettő egy futásban nem kombinálható.

## Word-képernyőképek

```text
python <skill>/scripts/tender_tools.py --extract-docx <kepernyokepek.docx> --outdir <kepek>
```

A `document.json` a bekezdések szövegét, a képfájlokat és a Wordben megadott linkeket sorolja fel; a kód nem végez OCR-t. **Nyisd meg és nézd meg a kinyert képeket**; a fájl megléte nem kiolvasás. Ha egy kép nem nyitható meg vagy olvashatatlan, jelezd, és kérj olvasható képet/exportot.

A látható sorokból készíts forrásonként normalizált JSON-t (fiktív sémapélda):

```json
{
  "status": "partial",
  "records": [{
    "id": "", "buyer": "A képen olvasható ajánlatkérő", "title": "A képen olvasható tárgy",
    "notice_type": "Indikatív ajánlatkérés", "deadline": "", "deadline_time": "", "framework": "",
    "procedure_type": "indikatív", "buyer_on_behalf": "", "value": "", "currency": "", "value_kind": "",
    "supplier": "", "procedure_status": "", "comment": "", "publication_date": "",
    "source_metadata": {"document": "kepernyokepek.docx", "image": "image_001.png", "visible_row": 1,
                        "extraction_notes": "A határidő nem olvasható."}
  }],
  "warnings": ["Egy határidő nem olvasható; a képek nem igazolják a portál teljes találati listáját."],
  "metadata": {"input_kind": "manual_screenshots", "coverage": "visible_rows_only"}
}
```

- `success`: minden átadott kép minden sora feldolgozható; `partial`: hiányos, levágott vagy bizonytalan adat. A siker csak az átadott anyagra vonatkozik, nem a teljes portálra.
- Teljesen olvashatatlan sor kihagyását számold meg a figyelmeztetésekben. Átfedő képek ismétlődő sorait ne duplázd; címhasonlóság nem bizonyít azonosságot. A forrástípust ne módosítsd azért, hogy az emailbe kerüljön.
- A kattintható tárgyhoz valódi, a sorhoz tartozó link kell; kék, aláhúzott szöveg a képen nem URL.

**Az üzleti adatokat a rekord felső szintjére írd, ne csak a metaadatba:**

| Látható oszlop | JSON-mező |
| --- | --- |
| Ajánlatkérő nevében eljár | `buyer_on_behalf` |
| Megrendelés / becsült érték | `value` |
| Pénznem, ha ténylegesen látszik | `currency` |
| Becsült vagy más értékjelölés | `value_kind` |
| KM | `framework` |
| Eljárás típusa | `procedure_type` |
| Számlakiállító szállító | `supplier` |
| Státusz | `procedure_status` |
| Megjegyzés | `comment` |

Az eredeti kiolvasást a `source_metadata.extracted_fields` alatt is megőrizheted; a kód az egyértelmű oszlopneveket onnan is átemeli, szöveges megjegyzésből nem. Üres Státusz cellánál a `procedure_status` üres marad (az aktív/indikatív besorolás külön adat). Pénznemet ne következtess az országból.

A JSON-ok és exportok egy futásban fűzhetők össze (`--source-input FORRÁS=<fájl>` és `--source-file FORRÁS=<fájl>`, forrásonként egy bemenet; azonos forrás több csatornájához lásd az `outlook_source.md` összevonási részét).

## Szűrés és értékelés

- A közös riportidőszak (SKILL.md) és a magyarországi teljesítési hely az elvárt szűrés. Kézi anyagnál ellenőrizd a látható szűrőket és közzétételi dátumokat; hiányukban a szűrést ne állítsd igazoltnak. A hiányzó teljesítési helyet ne azonosítsd az ajánlatkérő országával. A CPV-t őrizd meg, de ne szűrj kizárólag CPV-re.
- Hiányzó határidő nem bizonyít nyitottságot; jelezd az ellenőrzés szükségességét.
- A várt beszerzések táblája profil-kiegészítés, nem megjelent tenderlista: szemantikai értékeléshez használd, de forrástényként ne kerüljön az emailbe.
- A kézi anyag nem igazolja, hogy az összes aznapi találatot tartalmazza; a riport megőrzi a darabszámokat és a hiányos forrásokat.
