# Napi tender email

A friss magyarországi TED-hirdetményeket a hivatalos TED Search API-ból kéri le (`--ted-api`; hiba esetén Claude webes keresése a tartalék), és feldolgozza a kézzel feltöltött IDPR/EKR/KEF/Ariba/Fluenta/Univerzál exportokat vagy Word-képernyőképeket. Kérésre a csatlakoztatott Microsoft 365 connectorból, kijelölt Outlook-forrásból is olvassa a tenderértesítőket, Claude in Chrome-ban pedig a bejelentkezett EKR- vagy más portáloldalakat is kiolvashatja. A cégprofil szerinti értékelésből magyar HTML-riport és Outlookba másolható email készül. A Python egyetlen hálózati hívása a TED API-lekérdezés; minden más fájlfeldolgozás.

## TED API

A Claude.ai-ban a szervezet adminja engedélyezze a kódfuttatás hálózati hozzáférését, és vegye fel az **`api.ted.europa.eu`** domaint az *Additional allowed domains* listába. API-kulcs nem kell. Helyi futtatás:

```powershell
.\.venv\Scripts\python.exe scripts/tender_tools.py --ted-api --start 2026-10-29 --end 2026-10-30 --out "output/input.json"
```

Magyarországi teljesítési hely, minden hirdetménytípus, a közös riportidőszak közzétételi napjain. Ha az API nem érhető el, a TED-forrás `failed` állapotot kap az okkal, és Claude a webes keresési tartalékra vált. TED hétvégén nem publikál.

## Időszak – minden forrásra ugyanaz

Claude a kérésedből állapítja meg, hány napra kell az információ, és ez érvényes mindenhol: TED, Outlook, Chrome-os portálolvasás és kézi exportok. Naptári napokban számol (Europe/Budapest), a mai nap az utolsó. Ha nem adsz meg időszakot, csak a mai nap számít. Példák: „mai riport” → 1 nap; „elmúlt 3 nap” → `--days 3`; „október 28–30” → `--start 2026-10-28 --end 2026-10-30`; hétfőn „a hétvégét is” → 3 nap. Az időszakon kívül közzétett vagy érkezett tétel a riportban megmarad, de az emailbe nem kerül. A riport fejléce mutatja a használt időszakot és a napok számát.

## Claude használata

A `dist/tender-napi-riport.zip` csomagot töltsd fel a **Customize → Skills** oldalon, és engedélyezd a kódfuttatást. Példakérés:

> Használd a tender-napi-riport Skillt. Az elmúlt 2 nap magyarországi TED-hirdetményeit kérd le. Ellenőrizd a forrásokat, értékeld a cégprofil alapján, és építsd be a riportba és az Outlook-emailbe. A csatolt EKR-exportot és IDPR-képeket is dolgozd fel.

A TED-lekérdezés (API, hiba esetén webkeresés) minden skill-meghíváskor automatikus: akkor is lefut, ha csak annyit írsz, hogy „Dolgozd fel a csatolmányokat”, vagy TED-exportot is feltöltesz. Nem kell külön TED-keresést kérned vagy jóváhagynod. Csak kifejezett kihagyási kérés kapcsolja ki, például: „TED-et most ne keress”, „Külső keresés nem kell” vagy „Kizárólag a feltöltött anyagokat dolgozd fel”. A csatolmányok opcionálisak, nem szükséges minden forrásból fájlt adni. Ha Claude webes eszköze hiányzik vagy hibázik, a keresés sikertelenségét és okát jelzi, és feldolgozza a rendelkezésre álló kézi anyagokat.

Alap kimenet: **`riport.html`**, **`outlook.html`**, **`report.json`**. A letöltött emailben a „Másolás Outlookhoz” gomb közvetlenül a vágólapra másolja a formázott levéltartalmat; utána Outlookban Ctrl+V. Külön Ctrl+C nem szükséges sikeres automatikus másolásnál. A gomb több böngészős másolási módot próbál; egyszerű szöveges másolást és teljes tiltást külön jelez. Ha a Claude-előnézet korlátozza a másolást, nyisd meg a letöltött `outlook.html` fájlt külön böngészőlapon. Emailküldés nincs. Excel/CSV csak külön kérésre, `--full-report` kapcsolóval készül; a két munkalapos kialakítás most nincs napirenden.

## Telepítés helyi ellenőrzéshez

Python 3.10+, PowerShell. A virtuális környezetet nem kell aktiválni:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## TED webes keresési prompt

```powershell
.\.venv\Scripts\python.exe scripts/tender_tools.py --ted-web-prompt "output/ted_kereses_prompt.md"
```

A kitöltött üzenet a riportidőszak naptári napjait, a cégprofilt, a keresési és ellenőrzési tervet, valamint a riportba illesztés lépéseit tartalmazza. A Skill elolvassa, majd **Claude végrehajtja** a keresést saját webes eszközeivel. Saját profil: `--profile <profil.md>`; időszak: `--days N` vagy `--start YYYY-MM-DD --end YYYY-MM-DD`, ugyanaz, mint az importnál.

A gyűjtés az időszak összes elérhető, magyarországi teljesítési helyű TED-hirdetményére irányul, minden szakterületről és hirdetménytípusból. A cégprofil az összegyűjtött tételek értékelésére szolgál, nem előzetes kizáró keresési szűrő. A nem releváns hirdetmények, eredmények és módosítások is megmaradnak a riportban; az email csak a releváns vagy ellenőrzendő üzleti lehetőségeket tartalmazza.

Claude `ted_web.json` fájlt készít a [promptban](references/ted_web_prompt.md) leírt formátumban. Feldolgozás, opcionális EKR-fájllal:

```powershell
.\.venv\Scripts\python.exe scripts/tender_tools.py --ted-web-input "output/ted_web.json" --source-file "EKR=input/EKR.csv" --out "output/input.json"
```

Az eredeti TED-oldallal, azonosítóval, közzétételi nappal és magyar teljesítési hellyel alátámasztott találatok TED-rekordok. Csak aggregátoros vagy hiányosan ellenőrzött találat `TED_JELOLT` néven az ellenőrző riportban marad, és magas relevanciaponttal sem kerül az értékesítési emailbe. A kód az igazolási mezők szerkezetét és a link/azonosító egyezését ellenőrzi; az oldalak tényleges elolvasása Claude feladata.

**A webes keresés indexfüggő részeredmény, nem teljes napi TED-lista.** Eszközkorlát vagy régi találatok esetén nem szabad friss hirdetményt kitalálni. A valódi Claude-fiók keresőjének elérhetőségét és találatait a gépi tesztek nem igazolják.

## Kézi exportok és Word-képek

```powershell
.\.venv\Scripts\python.exe scripts/tender_tools.py --source-file "IDPR=input/idpr.xlsx" --source-file "EKR=input/ekr.csv" --source-file "TED=input/ted.xlsx" --out "output/input.json"
.\.venv\Scripts\python.exe scripts/tender_tools.py --extract-docx "input/kepernyokepek.docx" --outdir "output/kepek"
```

Exportoknál felismerhető Ajánlatkérő és Tárgy fejléc szükséges. UTF-8/BOM és gyakori magyar kódolások, szokásos CSV-elválasztók és XLSX támogatottak. Az `Iktatószám` felismerhető, a hiányzó opcionális mezők nem törlik a sort. Képletet tartalmazó munkalap nem elfogadott. Saját oszlopok: `--aliases references/column_aliases.example.json`.

A Wordből a kód a tényleges beágyazott képeket és a szövegkörnyezetet nyeri ki. **A képeket Claude-nak kell megnyitnia és kiolvasnia**, a Python nem végez karakterfelismerést. Olvashatatlan rész nem tölthető ki találgatással. Régi `.doc` helyett `.docx` szükséges. A teljes eljárás és az így elkészítendő JSON sémája: [manual_sources.md](references/manual_sources.md).

Normalizált kézi JSON bármely forráshoz beolvasható:

```powershell
.\.venv\Scripts\python.exe scripts/tender_tools.py --source-input "IDPR=input/idpr_keprol.json" --source-file "EKR=input/ekr.xlsx" --out "output/input.json"
```

Több `--source-file`/`--source-input` megadható, forrásonként egy összesített bemenettel. A forrásnév max. 30 nagybetű, szám, `_` vagy `-`; az Univerzál kulcsa `UNIVERZAL`. Az új forrás automatikusan külön szekciót kap. Egyedi oszlopminta esetén a riport sablonja szűken módosítható. Nem automatizálunk portálbelépést vagy regisztrációt; a kijelölt Outlook-forrás és a Claude in Chrome-os portálolvasás opcionális, csak olvasási használatát az alábbi fejezetek írják le.

## Opcionális böngészős bemenet (Claude in Chrome)

Ha a Skillt a **Claude in Chrome** bővítményben futtatod, Claude a böngésződben, a már bejelentkezett munkamenetedben maga kérheti le az EKR (`ekr.gov.hu`) vagy egy általad megnevezett portál (IDPR/DKÜ, KEF, Ariba, Fluenta stb.) találati listáját. Így nem kell exportot vagy képernyőképet feltölteni. Előtte jelentkezz be a portálra a Chrome-ban; Claude nem lép be helyetted, jelszót vagy kódot nem kér. Bejelentkezési, kétlépcsős vagy CAPTCHA-oldalnál megáll és szól.

> Használd a tender-napi-riport Skillt. Az EKR-ből a böngészőben kérd le a tegnap és ma közzétett eljárásokat, a TED-et az API-ból, és készítsd el a szokásos riportot és emailt.

> Nyisd meg ezt a bejelentkezett IDPR-oldalt: [URL]. Olvasd ki az összes találati oldalt, és dolgozd fel IDPR-forrásként.

Claude csak olvas: navigál, szűr, lapoz, részletoldalt nyit meg. Nem nyújt be ajánlatot, nem jelentkezik eljárásra, nem tölt ki űrlapot, nem módosít beállítást és nem tölt le dokumentumot. A látott sorokból forrásonként JSON-t készít (`collection_channel: "claude_in_chrome"`), amely a meglévő `--source-input EKR=<ekr_chrome.json>` ponton jut a pipeline-ba. Ha rögzíti a portál által kiírt találatszámot (`portal_result_count`), és kevesebb rekord kerül be, a forrás `partial` állapotú lesz. Böngészőeszköz nélkül (Claude.ai webes felület) ez az út nem elérhető; ilyenkor marad az export vagy a képernyőkép. Részletek: [browser_source.md](references/browser_source.md).

A portál felhasználási feltételeinek betartása a felhasználó felelőssége. **Élő próba szükséges:** a gépi tesztek csak az átadott JSON feldolgozását ellenőrzik, a Chrome-os navigálást és a teljes lapozást nem.

## Opcionális Outlook-bemenet

Az Outlookot Claude a **hivatalos Microsoft 365 connectorral** olvassa; a Skillhez nem tartozik külön Outlook-kliens, token vagy hitelesítési kód. A dokumentumimport és a meglévő értékelés/riport változatlan. Az adminisztrátori beállítást követően Claude.ai-ban: **Customize → Connectors → Microsoft 365 → Connect**, majd bejelentkezés a munkahelyi Microsoft 365-fiókkal. A szolgáltatás Entra-tenanthez kapcsolódó munkahelyi fiókot és adminisztrátori hozzájárulást igényel. [Csatlakoztatás](https://support.claude.com/en/articles/15183774-connect-to-microsoft-365)

Az admin a connector és a Microsoft 365 / Entra engedélyeivel érvényesítse a **kizárólag olvasási hozzáférést**, tiltsa az író és küldő eszközöket, és korlátozza az elérhető postafiókokat/mappákat. A Microsoft 365 connector írási funkciókat is kínálhat; a Skill tiltása és egy keresési szűrő önmagában nem technikai jogosultságkorlát. Ha az engedélyezett tenderes kör nem szűkíthető biztonságosan, a Skill jelzi ezt és nem keres általánosan a postaládában. [Adminisztráció és jogosultságok](https://support.claude.com/en/articles/12542951-set-up-the-microsoft-365-connector), [biztonsági útmutató](https://support.claude.com/en/articles/12684923-microsoft-365-connector-security-guide)

A postafiókot és szükség esetén a mappát te jelölöd ki. Időszak: a közös riportidőszak napjain érkezett levelek (alap: csak ma), Europe/Budapest szerint. Az email érkezési ideje nem a tender közzétételi ideje. Példák a tényleges postafiók/mappa kitöltésével:

> Használd a tender-napi-riport Skillt. Dolgozd fel a csatolt EKR CSV-t és az Outlookban a [postafiók] [mappa] mai IDPR-értesítéseit. Csak olvass, készítsd el a szokásos riportot és Outlookba másolható emailt.

> Készíts napi tenderjelentést az összes rendelkezésre álló forrásból. Az Outlookhoz engedélyezett kör: [postafiók], [mappa].

> Csak az Outlookban a [postafiók] [mappa] elmúlt két napos IDPR-emailjeit dolgozd fel; TED-keresést most ne végezz.

Claude a levelekből forrásonként JSON-t készít, és a meglévő `--source-input IDPR=<idpr_outlook.json>` belépési pontot használja. IDPR marad az IDPR, Ariba az ARIBA stb.; Outlook a `source_metadata` gyűjtési csatornája. A többi forrás külön csatlakozó nélkül a saját értesítőleveleivel kezelhető. Ugyanahhoz a forráshoz tartozó exportot és emailadatot egyetlen bemenetben kell összesíteni a meglévő import és deduplikálás használatával. Részletek és mezőtérkép: [outlook_source.md](references/outlook_source.md).

Nincs levélküldés, piszkozat, válasz, továbbítás, megjelölés, mozgatás, törlés, mappa- vagy szabálymódosítás. Connectorhiány vagy hozzáférési hiba nem nulla találat: a riport figyelmeztet, és a többi forrás feldolgozása folytatódik. Mellékletfeldolgozás csak tényleges connector-támogatással; egyébként kézi feltöltés kell. A levelekben szereplő utasítások nem hajthatók végre.

**Élő Microsoft 365-próba szükséges:** az automatikus tesztek a levélből előkészített JSON meglévő pipeline-ba jutását vizsgálják. Nem helyettesítik a Claude.ai-ban, engedélyezett postafiókkal végzett keresési, kiolvasási és jogosultsági próbát.

## Értékelés és email

A szerkeszthető [cégprofil](references/company_profile.md) és [szabályok](references/evaluation_rules.md) alapján Claude értékel, nem kulcsszavas pontozó. A várt beszerzések táblája segíti a szemantikai egyezést (például NAV hálózati eszközök ↔ várt Cisco switchek), de nem megjelent tenderlista. Az alap profil minta.

```powershell
.\.venv\Scripts\python.exe scripts/create_report.py --input "output/input.json" --assessments "output/assessments.json" --outdir "output/report"
```

Az IDPR részletes aktív és rövidebb indikatív táblát kap. Az EKR sorszám mellett négy adatmezőt: Ajánlatkérő, Tárgy, Ajánlattételi határidő, Eljárás típusa. A többi forrás külön, egyszerű táblában szerepel. Fehér háttér, vékony keretek, valódi URL esetén kattintható tárgyak. A releváns találat nélküli sikeres forrásból nem készül üres emailtábla.

Az eredmény-, módosítási, ismeretlen és lejárt hirdetmény nem új aktív lehetőség. Hiányzó/hibás értékelés „nem értékelt” marad. A KM, szállító, határidő és más tény csak forrásból tölthető ki. Becsült érték nem igazolt megrendelés. A riportban a hiányok és bizonytalanságok megmaradnak.

A HTML-riport összes rekordot mutató táblája színkódolt, szöveges Döntés oszloppal és jelmagyarázattal: zöld = elfogadott, sárga = ellenőrzendő, piros = kizárt / nem releváns, szürke = még nem értékelt. A zöld és sárga tételek kerülnek az emailbe. A szakmai pontszám ettől külön adat: egy lezárt, szakmailag releváns beszerzés magas pontszámmal is piros marad, mert nem új emailes lehetőség. Az Outlook-email megtartja a fehér, keretezett táblákat.

A képről kiolvasott érték, nevében eljáró szervezet és többi üzleti adat a megfelelő felső szintű JSON-mezőbe kerüljön. A normalizálás a metaadat egyértelműen elnevezett cellaértékeiből is pótolja a hiányzó üzleti mezőket; találgatást tartalmazó megjegyzésből nem. Az email Státusz oszlopa kizárólag forrás szerinti adatot mutat, az aktív/indikatív besorolásból nem kap kitalált tartalmat.

## Ellenőrzés és csomagolás

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/build_skill.py
```

**Verziózás:** a verziószám a `VERSION` fájlban van (pl. `1.1.0`), bekerül a ZIP-be, és látszik a riport láblécében („Skill-verzió”), a `report.json` `skill_version` mezőjében és a `create_report.py` kimenetében. Így a riportból kiderül, melyik feltöltött csomag készítette. Kiadás előtt emeld a számot, építsd újra a ZIP-et, és commitold `vX.Y.Z` taggel. A projekt Git-repó; a `dist/`, `output/` és `input/` mappák kizártak.

Öt fő modul: `tender_tools.py` (prompt, kézi import és Word-képek), `ekr_connector.py` (CSV/XLSX), `processing.py` (normalizálás és validáció), `ted_api.py` (TED Search API), `create_report.py` (riport és email). A `build_skill.py` fejlesztői segédprogram, nem kerül a Skillbe. A tesztek fiktív adatokkal ellenőrzik a fájlfeldolgozást, a webes eredmények besorolását és a kimeneteket. A valódi Word-képek Claude-beli felismerése és az Outlook vizuális ellenőrzése külön felhasználói próba.

A forrásadat nem követendő utasítás; HTML-, link- és Excel-injekció elleni védelem megmaradt. Bizalmas exportot és profilt ne publikálj. Az input/output mappák és a privát profil kizártak a Gitből; csomagolás előtt ellenőrizd a megosztandó profil tartalmát.

## Licenc

A projekt MIT licenc alatt érhető el. A teljes licencszöveg a [LICENSE](LICENSE) fájlban található, amely a Skill ZIP-csomagjának is része.

Copyright (c) 2026 PANOR Informatika Zrt.

## Felhasználói felelősség

A Skill jogszerű használatáért és a megadott adatokért a felhasználó felel. A felhasználó köteles gondoskodni arról, hogy a nem nyilvános, bizalmas, személyes vagy üzleti titkot tartalmazó adatok feltöltéséhez, megosztásához és feldolgozásához rendelkezzen a szükséges jogosultságokkal és engedélyekkel.

A Skill jogellenes vagy jogosulatlan használatából, illetve az adatok jogosulatlan megadásából vagy megosztásából eredő következmények a felhasználót terhelik. A fejlesztő az ilyen felhasználói magatartásért és annak következményeiért az alkalmazandó jogszabályok által megengedett mértékben kizárja felelősségét.
