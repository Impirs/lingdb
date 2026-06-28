# **Alat za kreiranje lokalne višejezične leksičke baze podataka zasnovanog na Wikirečnikovim dampovima**

# 1\. Definicija problema

Mnogi zadaci obrade prirodnog jezika (NLP) – mašinsko prevođenje, međujezična pretraga i jezičke aplikacije – zahtevaju višejezične rečnike i konceptualne baze podataka. Problem je u tome što su vredna rešenja poput BabelNet-a vlasnička i plaćena, dok rešenja otvorenog koda poput OMWN-a pružaju manju, čisto semantičku bazu podataka, kojoj nedostaju oblici reči, primeri upotrebe i fonogrami.  
Wikirečnik, u međuvremenu, sadrži milione članaka na desetinama jezika sa prevodima, sinonimima, primerima i oblicima reči – ali sve se to čuva kao sirovi XML/JSONL dampovi koji se ne mogu direktno koristiti.

Cilj projekta je da se napiše alat koji kreira lokalnu jezičku bazu podataka i univerzalni API za njegovu kasniju upotrebu.  
Gde se ovo može koristiti: prevodioci sa kontekstualnim objašnjenjima, platforme za učenje jezika, lingvistička istraživanja i podrška za jezike sa ograničenim resursima.

# 2\. Skup podataka

**Izvor:** [kaikki.org](http://kaikki.org) \- ovo su gotovi JSONL dampovi koji se automatski generišu iz zvaničnih XML dampova Wikimedije. To znači da su sirovi podaci već u pogodnom formatu, ali su i dalje veoma neuredni.

**Jezici:** 

1. Engleski (en)  
2. Nemački (de)  
3. Ruski (ru)

**Veličina:**

| Jezik  | Jedinstvene leme | Oblici reči  (sa paradigmama) |
| :---: | :---: | :---: |
| en | 1.366.224 | 1.390.268 |
| de | 955.050 | 2.799.417 |
| ru | 471.493 | 953.234 |

* Podaci su dobijeni direktnim upitima u moj lični PostgreSQL radni prostor, nakon delimičnog završetka prve faze analize.

Ovo je primer za englesku rec “encyclopedia” posle prevodjenja iz jsonl u json podaci. Pocetni JSONL podaci imaju mnogo vise ne upotrebljivih simbola, html tegova i uglastih zagrada.

{  
  "word": "encyclopedia",  
  "language": "English",  
  "language\_code": "en",  
  "part\_of\_speech": "noun",  
  "gender": null,  
  "definitions": \[  
    "The circle of arts and sciences (see Etymology); a comprehensive summary of knowledge, or of a branch thereof.", "...", "..."  
  \],  
  "examples": \[  
    {"text": "I only use the library for the encyclopedia, as we’ve got most other books here.", "type": "example", "reference": ""},  
    ...  
  \],  
  "translations": {},  
  "etymology": "...",  
  "forms": \[  
    {"form": "encyclopedias", "tags": \["plural"\], "source": ""}, {"form": "encyclopediae", "tags": \["plural"\], "source": ""},  
    {"form": "encyclopediæ", "tags": \["plural"\], "source": ""}, {"form": "encyclopaedia", "tags": \["alternative", "Commonwealth"\], "source": ""},  
    {"form": "encyclopædia", "tags": \["alternative", "dated"\], "source": ""}  
  \],  
  "synonyms": \[\],  
  "antonyms": \[\],  
  "related\_words": \["paideia", "Paidia", "-pedia", "pedo-", "dictionary", "pandect"\],  
  "hypernyms": \[\],  
  "hyponyms": \[\],  
  "meronyms": \[\],  
  "derived": \["encyclopedial", "encyclopedialike", "encyclopedian", "encyclopedic", "encyclopedical", "encyclopedic dictionary", "encyclopedic fiction", "encyclopedist", "-pedia", "walking encyclopedia", "Wikipedia", "xenoencyclopedia"\],  
  "coordinate\_terms": \[\]  
}\`

# 3\. Metodologija

Rezultat projekata je rezultat ETL pipeline (Izdvajanje \-\> Transformacija \-\> Učitavanje) sa analitičkim slojem na vrhu. Arhitektura je dizajnirana za proširenje: počinjem sa nekoliko jezika i dodajem nove bez ponovnog izgradnje baze podataka.

## Faza 1 \- Čišćenje i morfološka analiza

Ovo je najveća faza i sve ostalo zavisi od nje.  
Dampovi se čitaju red po red (strimovanje), jer datoteke mogu težiti nekoliko gigabajta. Prvo, filtriram sve nepotrebne informacije \- tehničke članke, unose bez vrednosti, unose na jezicima koji nisu potrebni. Wiki oznake se uklanjaju iz tekstova.  
Zatim se za svaki unos određuje lema (osnovni oblik reči) i vrši se morfološka analiza. Polje „pos“ u dampu često nedostaje ili je pogrešno popunjeno, jer pos reci zavisi od gramatici jezika, pa se koristi Stanza (alat za neuronske mreže koji podržava svih 5 jezika): on vrši POS tagovanje, lematizaciju i potpunu morfološku analizu koristeći univerzalne zavisnosti.  
Za ruski jezik se dodatno koristi pymorphy3 — brži je za izolovane oblike bez konteksta.  
Cela paradigma reči \- svi padeži, konjugacije sa oznakama \- izdvaja se iz polja „oblici“. Ovo je neophodno za pretragu po bilo kom obliku i pronalaženje leme.  
Primeri upotrebe se čiste i povezuju sa određenim značenjem reči, a ne samo sa celom rečju.  
Na kraju, dolazi do deduplikacije: jedna reč može biti opisana u više odeljaka Wikirečnika; spajamo ih pomoću ključa „(word, lang, pos)“.  
Dodavanje novog jezika \= registrovanje u konfiguraciji (kod, putanja za damp, morfološki bekend). Postojeći podaci nisu pogođeni.

## Faza 2 \- Konstrukcija grafa koncepata

Cilj je da se bilo koja reč u bazi podataka učini prevodivom na bilo koji drugi jezik putem grafa. Reči za koje nema dostupnih prevoda ni u jednom odeljku Wikirečnika (jedinstveni kulturni koncepti, izuzetna retkost) predstavljaju objektivno ograničenje podataka, a ne algoritamski problem. U praksi, prvih 10.000 reči na bilo kom jeziku pokrivaju \~95% govornog jezika i sve one imaju prevode.

Grafik G \= (V, E) se konstruiše:

* **čvorovi** \- značenja reči (smislovi) iz svih jezika \+ čvorovi koncepata  
* **ivice** \- \`translation\`, \`synonym\`, \`antonym\`, \`hypernym\`, \`hyponym\`

**Koncepti se konstruišu u četiri prolaza:**

1. Direktne ivice preko svih jezika \- prevodi iz svih dampova se koriste direktno, bez posrednika. Ako nemački članak prevodi reč na ruski i francuski, ove ivice se direktno dodaju grafu. Ne samo preko engleskog. Pouzdanost: 1.0.  
2. Tranzitivno zatvaranje \- ako je A \-\> B i B \-\> C, sva tri spadaju u isti koncept. Algoritam Union-Find sa kompresijom putanje \- radi brzo čak i na desetinama miliona grana.  
3. TF-IDF podudaranje glosa \- za reči koje imaju prevod na drugi jezik, ali nije jasno na koje značenje se odnosi. Glos (definicija) se upoređuje sa glosima kandidata i bira se najsličniji. Pouzdanost: 0,85.  
4. LaBSE za preostale \- reči bez jedne prevodne grane dobijaju ugrađivanje svoje definicije putem višejezičnog LaBSE modela. Ako je ugrađivanje dovoljno blizu postojećem konceptu, reč se spaja sa njim. Pokreće se odvojeno nakon glavnog pipeline. Pouzdanost: 0,70.

Prilikom dodavanja novog jezika, samo novi unosi se obrađuju i spajaju sa postojećim konceptima; ništa se ne preračunava.

## Faza 3 \- Analitika

Nakon izgradnje baze podataka, možete:

* Pronaći prevode reči na bilo koji jezik (direktno i preko posrednih koncepata)  
* Dobiti klaster sinonima \- sve reči jednog koncepta na svim jezicima  
* Pregledati statistiku: pokrivenost vokabulara, gustina grafa, prazni koncepti

## Faza 4 \- Skladištenje

* Sve je sačuvano u bazu podataka. Glavne tabele:  
* languages \- jezički registar  
* words \- leme  
* senses \- koncepti \- međujezički koncepti  
* relations \- ivice grafa sa tipom i težinom  
* forms, examples \- oblici reči i primeri

# 4\. Metod evaluacije

1. **Pokrivenost**   
   Izračunato SQL upitom preko cele tabele:  
* % reči kojima je dodeljen concept — ukupna pokrivenost;  
* Razvrstavanje po prolazima: koliko reči je uključeno u prolaz 1 (direktne ivice), koliko je uključeno u TF-IDF, koliko je uključeno u LaBSE i koliko je ostalo kao završeci;  
* Distribucija pouzdanosti: koliko koncepata ima težinu od 1,0 / 0,85 / 0,70.  
2. **Poređenje sa benčmarkovima**  
   Koriste se dva otvorena skupa podataka sa unapred određenim tačnim odgovorima:  
   [MUSE](https://github.com/facebookresearch/MUSE) \- Facebook Research, verifikovani prevodni parovi za en-de, en-ru. Sadrži \~100.000 parova za svaki jezički par.  
   [Open Multilingual Wordnet](http://omwn.org/) \- provera poravnanja koncepata. Ako naš koncept X kombinuje iste reči kao sinset u OMW, poravnanje je ispravno. F1 se izračunava na osnovu podudaranja skupa.  
3. **Test Svadeš liste**  
   Svadeš lista sadrži 207 osnovnih koncepata (voda, vatra, ruka, ići itd.) prisutnih u svim jezicima sveta. Oni uvek imaju tačan prevod; dobro su poznati. Ovo se proverava ručno, ali na malom i reprezentativnom uzorku, ovo je značajno, za razliku od slučajnog uzorka od 500 reči od 10 miliona.  
4. **Strukturne metrike grafa**  
* **Prosečna gustina jezika koncepta** \- Koliko je jezika u proseku predstavljeno u jednom konceptu. Cilj: bliže 5 za bazu podataka od 5 jezika;  
* **Udeo izolovanih koncepata (1 jezik)** \- sto je broj manji, bolja je pokrivenost;  
* **Veličina najveće povezane komponente** \- ako je graf jako fragmentiran, postoji problem sa algoritmom;  
* **Distribucija veličina koncepata** \- nenormalno veliki koncepti (1000+ reči) ukazuju na pogrešno spajanje homonima.

# 5\. Tehnologije

| Jezik | Python 3.14 |
| :---: | :---: |
| Baza podataka | PostgreSQL 18 |
| Graf | NetworkX |
| ETL | pandas, tqdm, ijson |
| Morfologija | Stanza \+ pymorphy3 |
| Drajver baze podataka | psycopg3 |
| GUI (opciono) | Electron |
| VCS | Git |

# 6\. Primeri postojećih rešenja

[BabelNet](https://babelnet.org) \- najbliži analog, komercijalni, zatvoren  
[Open Multilingual Wordnet](http://omwn.org) \- otvoren, ali malo jezika i samo semantic graph  
[ConceptNet](https://conceptnet.io) \- graf zdravog razuma (smisla), ima prevode, ali nema podataka bas o vokabularu i gramatici  
[kaikki.org](http://kaikki.org) \- izvor podataka za projekat, ne generiše koncepte sam  
[Wiktextract](https://github.com/tatuylonen/wiktextract) \- parser koji koristi kaikki

# 7\. Literatura

1. Navigli, R., & Ponzetto, S. P. (2012). \*BabelNet: The automatic construction, evaluation and application of a wide-coverage multilingual semantic network\*. Artificial Intelligence, 193, 217–250. [doi:10.1016/j.artint.2012.07.001](https://doi.org/10.1016/j.artint.2012.07.001)  
2. Bond, F., & Foster, R. (2013). \*Linking and extending an open multilingual wordnet\*. ACL 2013\. [aclanthology.org/P13-1133](http://aclanthology.org/P13-1133)  
3. Qi, P., et al. (2020). \*Stanza: A Python Natural Language Processing Toolkit for Many Human Languages\*. ACL 2020\. [arxiv.org/abs/2003.07082](http://arxiv.org/abs/2003.07082)  
4. Joulin, A., et al. (2018). \*Loss in Translation: Learning Bilingual Word Mapping with a Retrieval Criterion\*. EMNLP 2018\. [arxiv.org/abs/1804.07745](http://arxiv.org/abs/1804.07745)