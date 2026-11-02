# Outlook mint opcionális bemeneti csatorna

Claude a hivatalos Microsoft 365 connectort használja; a Python csak a belőle készült JSON-t olvassa. Első cél az IDPR/DKÜ; Ariba, Fluenta, Univerzál és KEF levelei ugyanígy kezelhetők. A skillutasítás viselkedési szabály, nem jogosultsághatár: a csak olvasási hozzáférést és a postafiók-kört az adminnak kell beállítania (README).

## Mikor és milyen körben olvass?

- Csak a felhasználó ilyen kérésére vagy „az összes rendelkezésre álló forrás” esetén. A postafiók és opcionális mappa a kérésből vagy korábbi egyértelmű kijelölésből jöjjön; hiányában célzottan kérdezz rá (a többi feldolgozás folytatódhat). Cégprofilból vagy töredékes meetingjegyzetből ne találj ki postafiókot.
- **Időszak:** a SKILL.md közös riportidőszaka naptári napokban: az első nap 00:00-tól az utolsó nap 23:59-ig *érkezett* levelek (nem a tender közzététele). A `source_metadata.email.received_at` mezőt mindig töltsd ki; a kód ez alapján ellenőrzi az időszakot.
- Csak a munkamenetben ténylegesen elérhető connector-eszközöket és paramétereiket használd; eszköznevet vagy keresőszintaxist ne találj ki.
- A keresést már a kérésben szűkítsd a kijelölt postafiókra/mappára (eszközparaméterrel vagy igazolt admin-korláttal). Feladó-, tárgy- vagy dátumszűrő nem mappahatár. Ha a kijelölés nem érvényesíthető, ne keress a teljes postaládában, hanem jelents szűkítési korlátot.
- A kijelölt körben **minden levelet olvass el, és mindegyik kerüljön a riportba**: tenderértesítő a portál forrása alatt, egyéb levél `OUTLOOK` „nem tender” tételként. Körön kívüli levelet ne nyiss meg. A tényleges feladói címet és tartalmat vizsgáld; a megjelenített név vagy a keresési kivonat nem elég. Járd be az összes találati oldalt; találatkorlát vagy kihagyott oldal = részleges gyűjtés.
- Csak olvass: nincs küldés, válasz, továbbítás, piszkozat, olvasottnak jelölés, kategorizálás, mozgatás, törlés, mappa- vagy szabálymódosítás, portálbelépés. Mellékletet csak tényleges connector-támogatással olvass (különben kérj kézi feltöltést); távoli nyomkövető képlinkeket ne kövess.

## Átadás

Forrásonként egy JSON-boríték a `manual_sources.md` sémájával. A rekordok forrása az eredeti portál (`IDPR`, `ARIBA`, `FLUENTA`, `UNIVERZAL`, `KEF`); Outlook csak gyűjtési csatorna. Kivétel a nem tender levelek `OUTLOOK` borítékja. Ha egy tenderértesítő portálja nem állapítható meg, ne tippeld meg: kérj pontosítást, és a hozzá nem rendelt levelek számát írd a figyelmeztetésekbe.

A `metadata.messages_read` a borítékba felvett különböző levelek száma; a kód összeveti a rekordok `source_metadata.email.message_id` értékeivel, eltérésnél részleges állapotot és figyelmeztetést ad. A borítékok összege egyezzen az összes elolvasott levéllel; ezt az összefoglalóban is közöld.

| Levélből igazolt adat | Rekordmező |
| --- | --- |
| Beszerzés azonosítója | `id` |
| Ajánlatkérő, nevében eljáró szervezet | `buyer`, `buyer_on_behalf` |
| Tárgy, műszaki leírás | `title`, `description` |
| Ajánlattételi / részvételi határidő és idő | `submission_deadline`, `deadline_time` |
| Teljesítési határidő | `performance_deadline` |
| Becsült érték, pénznem, érték jellege | `value`, `currency`, `value_kind` |
| Beszerzés tényleges URL-je | `url` |
| Hirdetménytípus, eljárás típusa, forrásbeli státusz | `notice_type`, `procedure_type`, `procedure_status` |
| KM, szállító, megjegyzés, CPV, teljesítési hely | `framework`, `supplier`, `comment`, `cpv`, `performance_place` |
| Tender-közzététel, ha a levél külön közli | `publication_date` |
| Érkezés, feladó, email-azonosító, emailhivatkozás | `source_metadata.email` |

Az érkezést soha ne írd a `publication_date` mezőbe; teljesítési határidőt ne írj ajánlattételi határidőnek; „új értesítés” tárgyból ne következtess aktív státuszra; üres forrásbeli Státusz üres marad. Csak linket tartalmazó értesítőből hiányos rekord készülhet (`partial` forrás, ismeretlen típus, így nem kerül az emailbe).

Fiktív sémapélda (a `message_id`, postafiók, mappa és `message_url` csak tényleges connector-adat lehet):

```json
{
  "status": "partial",
  "metadata": {"collection_channel": "outlook_connector", "mailbox": "tender-fiok@example.org", "folder": "Tender/IDPR",
               "messages_read": 1, "coverage": "selected_scope_only"},
  "records": [{
    "id": "FIKTIV-IDPR-001", "buyer": "Fiktív intézmény", "title": "Vállalati hálózati eszközök beszerzése",
    "notice_type": "Ajánlati felhívás", "procedure_type": "Versenyújranyitás", "procedure_status": "",
    "submission_deadline": "2026-11-12 10:00", "deadline_time": "10:00", "performance_deadline": "2027-02-28",
    "publication_date": "", "value": "48000000", "currency": "HUF", "value_kind": "becsült érték",
    "url": "https://example.org/fictional/idpr/001",
    "source_metadata": {"collection_channel": "outlook_connector", "email_item_index": 1,
      "email": {"message_id": "fiktiv-email-001", "sender": "ertesito@example.org", "subject": "FIKTÍV IDPR versenyújranyitás",
                "received_at": "2026-10-30T08:15:00+01:00", "message_url": ""}}
  }],
  "warnings": ["A levél nem közöl tender-közzétételi dátumot."]
}
```

### Nem tender levelek

Hírlevél, rendszerüzenet, belső levél, számla, visszaigazolás stb. egy-egy rekordot kap egy külön `OUTLOOK` borítékban, `"notice_type": "nem tender"` jelöléssel: `title` = a levél tárgya, `source_metadata` = `email_item_index`, rövid `not_tender_reason` és az `email` adatai (azonosító, feladó, tárgy, érkezés). A levél törzsét ne másold be. A kód automatikusan 0 pontot ad (lila „Nem tender” sor, sosem kerül az emailbe); értékelés nem kell, ha mégis írsz, csak 0 lehet. Ha bizonytalan, hogy tender-e, ne jelöld „nem tender”-nek: vedd fel a portál alatt ismeretlen típussal. Import: `--source-input OUTLOOK=<outlook_nem_tender.json>`.

## Import és azonos források összevonása

```text
python <skill>/scripts/tender_tools.py --days <N> --ted-api --source-input IDPR=<idpr_outlook.json> --source-file EKR=<ekr.csv> --out <input.json>
```

További portálokhoz ugyanígy `--source-input ARIBA=...`, `FLUENTA=...` stb. Ha ugyanahhoz a portálhoz export/kép és email is van, ne adj két `IDPR` bemenetet, és ne nevezz át forrást: az exportot `ekr_connector.import_ekr(..., source='IDPR')`, a JSON-t `tender_tools.import_source('IDPR', ...)` olvassa be, és a listákat `tender_tools.dedup` fűzi egy borítékba; a csatornák állapota és korlátai a `metadata.channels` és `warnings` mezőkbe kerüljenek. Egyező tényleges azonosítónál a megtartott rekordban őrizd meg az email eredetét is; ellentmondó tényt ne írj felül, hanem jelezd.

Duplikációhoz a tényleges tenderazonosítót használd. Ha nincs, az `id` üres marad (a kód hash-kulcsot ad); ehhez a `source_metadata` csak stabil levélmetaadatot és a levélen belüli `email_item_index`-et tartalmazza (több tender egy levélben: külön index, eredeti sorrendben). Email-azonosító nem tenderazonosító. Címhasonlóság alapján ne vonj össze. Napi riportok közötti előzmény-összevetést ne ígérj.

## Státusz

- `success`: a kijelölt kör és időszak bejárható volt, minden levél feldolgozva. Üres `records` csak ekkor jelent „nem érkezett értesítés”.
- `partial`: találatkorlát, kimaradt oldal/levél/melléklet, hiányos adat, bizonytalan forrás, vagy egy csatorna hibája a másik sikere mellett.
- `failed`: nincs connector, hozzáférés vagy érvényesíthető kör; üres rekordlista és a tényleges ok, pl. `{"status":"failed","metadata":{"collection_channel":"outlook_connector"},"records":[],"warnings":["A tényleges hiba."]}`. Ez a többi forrással együtt importálható. Ha ugyanannak a portálnak sikeres kézi anyaga is van, a közös állapot `partial`, a hiba a csatornametaadatokba kerül.
- `not_attempted`: nem kérték vagy kihagyatták; ilyenkor ne nyiss postaládát.
