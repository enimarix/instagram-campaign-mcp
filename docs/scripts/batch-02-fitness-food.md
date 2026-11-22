# Batch 02: fitness, food, calories, muscle (12 scripts)

Written 2026-11-19 and reworked the same day after the owner's review. Most of the batch now runs on the 3D engines:

| Engine | Count | Scripts |
|---|---|---|
| Blender (CinematicSkit) | 5 | 2, 3, 9, 10, 11 |
| Voxel (VoxelQuest) | 3 | 4, 5, 6 |
| Pixel | 3 | 1, 8, 12 |
| Paper | 1 | 7 |

**Rules applied:**
- Formats and lengths vary, from a 10 s gag to a 70 s explainer.
- macroBody is mentioned only where a real feature fits:
  - barcode scan
  - AI photo logging
  - "Complete my day"
  - protein target
- Every video ends on a send-to-a-friend line:
  - Voxel videos speak it as the outro.
  - Everywhere else it opens the caption.
- All lines fit their template limits:
  - Blender: line ≤ 80 characters, outro ≤ 60.
  - Voxel: hook and outro ≤ 70 characters, beat ≤ 90, food label ≤ 14.

**Production:** nothing renders until the owner says start. Each video then goes through `create_idea` → `render_motion` (with the project's TTS) → QC → `submit_asset` with its caption, and lands in the app's review inbox.

⚠ marks a figure or source page not yet opened: it is checked on WebFetch before its idea is created, as the produce playbook requires.

| # | Video | Engine / template | Length | Address | macroBody | Share target |
|---|---|---|---|---|---|---|
| 1 | Manger après 20 h | pixel BossBattle | ~20 s | vous | caption | the one who won't eat after 8 pm |
| 2 | Ton frère et ses 100 crunchs | **Blender** teen | ~15 s | tu | caption | the crunch-since-January friend |
| 3 | Papa et les courbatures | **Blender** dad | ~18 s | tu | — | the "no pain, no gain" friend |
| 4 | 4-4-9-7 | **voxel** | ~30 s | vous | barcode scan | the one who does the maths in their head |
| 5 | Le bol « healthy » | **voxel** | ~28 s | vous | AI photo | the bowl-of-the-day friend |
| 6 | 2 œufs, et c'est tout ? | **voxel** | ~28 s | vous | Complete my day | the "2 eggs is enough" friend |
| 7 | Jus d'orange | paper | ~30 s | vous | app beat | the "it's healthy" juice drinker |
| 8 | Le muscle ne grandit pas à la salle | pixel FactQuest, long | ~70 s | vous | protein target | the 7/7 no-rest friend |
| 9 | Maman et les pâtes | **Blender** mum | ~18 s | tu | — | your mum |
| 10 | Mamie digère allongée | **Blender** grandma | ~15 s | tu | — | the post-lunch napper |
| 11 | Papa a lu une méta-analyse | **Blender** dad, long | ~40 s | tu | — | the "3 sets on Monday" friend |
| 12 | 1 min ou 3 min de repos ? | pixel BossBattle | ~30 s | vous | — | the one who rushes you between sets |

---

## 1. Manger après 20 h fait grossir ? — pixel BossBattle, ~20 s, vous

- **Hook:** « Manger après 20 h fait grossir ? »
- **MYTHE:** « Après 20 h, tout ce que vous mangez se transforme en gras ! »
- **RÉALITÉ:** « Votre corps ne lit pas l'heure : c'est le total de la journée qui compte. »
- **RÉALITÉ:** « Le vrai piège du soir, c'est le grignotage en plus des repas. Pas l'horloge. »
- **Verdict:** « Mythe. Dîner à 21 h ne change rien si votre journée est équilibrée. »
- **Tagline:** « Vos calories, sur toute la journée »
- **Caption:** 📩 Envoyez ça à celui qui refuse de manger après 20 h. Dîner tard ne fait pas grossir en soi : c'est le bilan de la journée qui compte (c'est d'ailleurs ce que macroBody suit, pas l'heure).
- **Source:** Kinsey & Ormsbee 2015, Nutrients 7(4) — https://doi.org/10.3390/nu7042648

## 2. POV : ton frère fait 100 crunchs pour l'été — Blender, teen, ~15 s, tu

- **Hook (silent):** « POV : ton frère fait 100 crunchs par jour pour l'été »
- **Lines:**
  1. « Cent crunchs par jour. Dans deux semaines, j'ai les abdos. »
  2. « Deux semaines plus tard… Ils sont là, je le sens. Juste en dessous. »
  3. « En dessous de quoi ? … Laisse tomber. Passe-moi le pain. »
- **Outro (card):** « Le ventre plat, ça se joue à table »
- **Caption:** 📩 Envoie ça à ton pote qui fait des crunchs depuis janvier. Les crunchs musclent les abdos, mais le gras du ventre ne part pas pour autant : il part partout à la fois, avec un léger déficit calorique (macroBody te le calcule).
- **Source:** Vispute et al. 2011, *The effect of abdominal exercise on abdominal fat*, J Strength Cond Res 25(9) ⚠

## 3. POV : papa juge ta séance à tes courbatures — Blender, dad, ~18 s, tu

- **Hook (silent):** « POV : papa juge ta séance à tes courbatures »
- **Lines:**
  1. « T'arrives à descendre l'escalier ? Alors t'as pas travaillé. »
  2. « Moi, à ton âge, j'avais mal trois jours. Ça, c'était du sport ! »
  3. « Quoi, les courbatures prouvent rien ? … Bon. Passe-moi le poulet. »
- **Outro (card):** « Progresser sans souffrir pour rien »
- **Caption:** 📩 Envoie ça à quelqu'un qui pense que « pas mal = pas de résultat ». Les courbatures baissent quand ton corps s'habitue, même si tu progresses.
- **Source:** Schoenfeld & Contreras 2013, Strength Cond J 35(5) ⚠ — https://doi.org/10.1519/SSC.0b013e3182a61820

## 4. 4, 4, 9, 7 : le code secret des calories — voxel, ~30 s, vous

- **Settings:** hookProp `plate` · accent `kcal` · forms `recrue` → `combattant`
- **Hook:** « 4, 4, 9, 7 : le code secret des calories »
- **Beats:**
  - **problem:** « Protéines et glucides : 4 kcal le gramme. Lipides : 9. Alcool : 7. »
    - foods: egg « 4 kcal/g » (protein) · riceBowl « 4 kcal/g » (carbs) · avocado « 9 kcal/g » (fat)
  - **problem:** « Grammes × 4, × 4, × 9… Faire ça à chaque étiquette, c'est long. »
  - **app:** « Encore plus simple : scannez le code-barres dans macroBody, tout est compté. » · value « 0 calcul »
  - **payoff:** « Plus de calcul de tête. Un scan, et c'est fait. »
- **Outro (spoken):** « Envoyez ça à celui qui calcule tout de tête ! »
- **Caption:** 📩 Envoyez ça à quelqu'un qui lit toutes les étiquettes au supermarché. Grammes × 4, 4, 9 ou 7 = calories, ou un scan dans macroBody.
- **Sources:**
  - FAO 2003, *Food energy – methods of analysis and conversion factors*, ch. 3 — https://www.fao.org/4/y5022e/y5022e04.htm
  - *Atwater system* — https://en.wikipedia.org/wiki/Atwater_system

## 5. Votre bol « healthy » : où sont les calories ? — voxel, ~28 s, vous

- **Settings:** hookProp `plate` · accent `fat` · forms `etincelle` → `recrue` · cameo `avocado`
- **Hook:** « Votre bol « healthy » : devinez le plus calorique »
- **Beats:**
  - **problem:** « Brocoli, poulet, avocat. Le bol parfait… mais qui pèse le plus ? »
    - foods: broccoli « ≈ 35 kcal » · drumstick « ≈ 165 kcal » (protein) · avocado « ≈ 240 kcal » (fat)
  - **problem:** « L'avocat entier, devant le poulet. Bon pour vous, mais pas léger. »
  - **app:** « Une photo du bol dans macroBody, et tout est compté. » · value « 440 kcal »
  - **payoff:** « Le bol reste au menu. Il est juste compté. »
- **Outro (spoken):** « Envoyez ça à votre pote qui mange un bol tous les midis ! »
- **Caption:** 📩 Envoyez ça à quelqu'un qui commande un poke bowl tous les midis. L'avocat est plein de bons gras, et donc de calories : un entier dépasse souvent le poulet.
- **Sources (USDA FoodData Central, to check ⚠):**
  - Avocado, raw: 160 kcal/100 g; flesh of 1 avocado ≈ 150 g
  - Chicken breast, roasted: 165 kcal/100 g
  - Broccoli: ≈ 35 kcal per 100 g

## 6. 2 œufs le matin, et c'est tout ? — voxel, ~28 s, vous

- **Settings:** hookProp `plate` · accent `protein` · forms `recrue` → `combattant`
- **Hook:** « 2 œufs le matin : 12 g. Votre cible ? 120 g. »
- **Beats:**
  - **problem:** « Deux œufs et une tartine d'avocat : à peine 15 g de protéines. »
    - foods: egg « 12 g » (protein) · avocado « ≈ 2 g » (protein)
  - **problem:** « À 75 kg, si vous vous entraînez, le repère tourne autour de 120 g par jour. »
  - **app:** « macroBody voit ce qu'il manque et vous propose de quoi finir la journée. » · value « 120 g »
  - **payoff:** « Poulet le midi, skyr au goûter : cible atteinte. »
- **Outro (spoken):** « Envoyez ça à celui qui pense que 2 œufs suffisent ! »
- **Caption:** 📩 Envoyez ça à quelqu'un qui « mange protéiné » avec deux œufs par jour. Le repère des études : environ 1,6 g par kg et par jour quand on s'entraîne.
- **Sources:**
  - USDA FDC, Egg, whole, raw (12.6 g/100 g; one 50 g egg ≈ 6 g) — https://fdc.nal.usda.gov/food-details/171287/nutrients
  - Morton et al. 2018, Br J Sports Med — https://bjsm.bmj.com/content/52/6/376
  - USDA avocado protein ≈ 2 g/100 g ⚠

## 7. Votre jus d'orange cache 4 morceaux de sucre — paper, ~30 s, vous

- **Character:** paul
- **Hook:** « Paul boit un jus d'orange. » / **« Il cache 4 sucres. »** · aside « (et c'est du sucre « libre ») »
- **Problem:** « Un verre de 25 cl… » / **« ≈ 21 g de sucres. »**
- **Problem:** « Pour l'OMS, le sucre du jus compte comme du sucre libre. » · aside « (comme celui d'un soda) »
- **App:** « macroBody affiche les glucides de chaque verre… » / « …et de chaque repas. » · value « 21 g »
- **Payoff:** « Cette semaine : 1 orange entière. » · stamp « MIEUX. »
- **Outro:** « Vos sucres, sans surprise »
- **Caption:** 📩 Envoyez ça à quelqu'un qui boit son jus « parce que c'est sain ». Le jus garde le sucre du fruit mais perd une bonne partie des fibres.
- **Sources:**
  - WHO 2015 sugars guideline — https://www.who.int/publications/i/item/9789241549028
  - USDA FDC orange juice ⚠

## 8. Votre muscle ne grandit pas à la salle — pixel FactQuest, ~70 s, vous

This is the long explainer: five levels, each read in full by the voice.

- **Hook:** « Votre muscle ne grandit pas à la salle »
- **Levels:**
  1. **Le signal:** « À la salle, vous envoyez juste un signal : une charge lourde, des séries qui finissent dures. »
  2. **Le chantier:** « Le muscle se construit après, pendant 1 à 2 jours : c'est là qu'il fabrique ses protéines. »
  3. **Les briques:** « Sans briques, pas de chantier : visez environ 1,6 g de protéines par kg et par jour. »
  4. **La nuit:** « Une seule nuit blanche a suffi à faire baisser cette construction de 18 % dans une étude. »
  5. **La suite:** « Et la semaine d'après ? Un peu plus de poids ou une rep de plus. Sinon, le signal s'éteint. »
- **Outro:** « Envoyez ça à votre pote qui s'entraîne 7 jours sur 7 ! »
- **Caption:** 📩 Envoyez ça à quelqu'un qui ne prend jamais de jour off. La salle donne l'ordre, le repos et l'assiette font le travail. macroBody calcule votre cible de protéines et vous montre ce qu'il manque.
- **Sources:**
  - MacDougall et al. 1995, Can J Appl Physiol 20(4) ⚠
  - Morton et al. 2018 — https://bjsm.bmj.com/content/52/6/376
  - Lamon et al. 2021, Physiol Rep 9(1) ⚠ — https://doi.org/10.14814/phy2.14660

## 9. POV : maman sert les pâtes « à l'œil » — Blender, mum, ~18 s, tu

- **Hook (silent):** « POV : maman sert les pâtes « à l'œil » »
- **Lines:**
  1. « Je t'ai mis 100 grammes, comme d'habitude. »
  2. « Comment ça, 100 grammes crus ou cuits ? C'est pareil, non ? »
  3. « Elles doublent, voire triplent en cuisant ?! … Bon, ressers-toi quand même. »
- **Outro (card):** « Cru ou cuit, enfin clair »
- **Caption:** 📩 Envoie ça à ta mère, elle se reconnaîtra. 100 g de pâtes crues ≈ 370 kcal. Cuites, elles pèsent 2 à 3 fois plus pour les mêmes calories.
- **Source:** USDA FDC, pasta dry (≈ 371 kcal/100 g) vs cooked (≈ 158 kcal/100 g) ⚠

## 10. POV : mamie digère allongée — Blender, grandma, ~15 s, tu

- **Hook (silent):** « POV : mamie fait sa sieste juste après le dessert »
- **Lines:**
  1. « Après manger, on s'allonge. On a toujours fait comme ça. »
  2. « Deux minutes de marche ? Pour quoi faire ? »
  3. « Ça fait baisser le sucre après le repas ? … Bon. Je fais le tour de la table. »
- **Outro (card):** « Même 2 minutes, ça compte »
- **Caption:** 📩 Envoie ça à celui qui fait la sieste direct après le dessert. Une petite marche juste après le repas, même de 2 à 5 minutes, réduit le pic de glycémie.
- **Source:** Buffey et al. 2022, Sports Medicine 52 ⚠ — https://doi.org/10.1007/s40279-022-01649-4

## 11. POV : papa a lu une méta-analyse sur la muscu — Blender, dad, ~40 s, tu

The long Blender video: six lines of real training advice, carried by the dad character.

- **Hook (silent):** « POV : papa a lu une méta-analyse sur la muscu »
- **Lines:**
  1. « Trois séries de pompes le lundi, et tu t'étonnes de pas grossir ? »
  2. « Pour un muscle, on compte par semaine. Pas par séance. »
  3. « Les études disent : dix séries dures ou plus par semaine. Pas trois. »
  4. « Pas d'un coup, hein. Cinq le lundi, cinq le jeudi. »
  5. « Et tu t'arrêtes quand il te reste une ou deux reps. Pas dix. »
  6. « … Oui, j'ai lu une méta-analyse. Mange ta soupe. »
- **Outro (card):** « Comptez vos séries par semaine »
- **Caption:** 📩 Envoie ça à quelqu'un qui fait « bras » une fois par semaine et s'étonne de ne pas progresser. Le repère des études : environ 10 séries dures par muscle et par semaine, en 2 séances ou plus.
- **Source:** Schoenfeld, Ogborn & Krieger 2017, J Sports Sci 35(11) ⚠ — https://doi.org/10.1080/02640414.2016.1210197

## 12. 1 minute ou 3 minutes de repos ? — pixel BossBattle, ~30 s, vous

- **Hook:** « 1 minute de repos entre les séries ? »
- **MYTHE:** « Pas plus d'une minute, sinon le muscle refroidit ! »
- **RÉALITÉ:** « Chez des pratiquants entraînés, 3 min de repos ont fait plus grossir les muscles qu'1 min. »
- **RÉALITÉ:** « Plus reposé, vous faites plus de reps à la série suivante. Donc plus de travail au total. »
- **Verdict:** « Sur les gros exercices, prenez 2 à 3 minutes. Le chrono n'est pas votre coach. »
- **Tagline:** « Le repos fait partie de la séance »
- **Caption:** 📩 Envoyez ça à celui qui vous presse entre deux séries. Squat, développé, rowing : prenez votre temps. Sur les petits exercices, 1 à 2 minutes suffisent souvent.
- **Source:** Schoenfeld et al. 2016, J Strength Cond Res 30(7) ⚠ — https://doi.org/10.1519/JSC.0000000000001272
