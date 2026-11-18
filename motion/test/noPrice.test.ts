import assert from "node:assert/strict";
import { test } from "node:test";
import { noPrice } from "../src/lib/noPrice.ts";

test("noPrice refuses amounts, currencies and per-period wording", () => {
  for (const bad of ["9,99 €", "€9", "4.99$", "10 euros", "12 EUR", "seulement 5 dollars", "4,99 / mois", "60 par an",
    "abonnement par mois", "$5 a month", "2,49"]) {
    assert.equal(noPrice(bad), false, bad);
  }
});

test("noPrice lets nutrition text through", () => {
  for (const ok of ["7 jours gratuits", "308 kcal restantes à 21 h", "1,6 g par kg", "72,4 kg", "31 g de protéines",
    "Le 2e jour", "macrobody.fr", "Sans engagement", "0,25 l", "1,75 m"]) {
    assert.equal(noPrice(ok), true, ok);
  }
});
