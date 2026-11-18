// French typography for every text the templates draw (= french_spaces in
// src/studio/recipe.py): a no-break space before ? ! : ; and » and after «, so wrapping
// never leaves the mark alone at a line start. Only a space already there before ? ! : ;
// changes, so English "Why?" stays as is. Wrapping (lib/typewriter.ts wrap) breaks at
// plain spaces only.
const NBSP = "\u00a0";

export const frenchSpaces = (text: string): string =>
  text
    .replace(/«[ \u00a0]*/g, `«${NBSP}`)
    .replace(/[ \u00a0]*»/g, `${NBSP}»`)
    .replace(/ +([?!:;])/g, `${NBSP}$1`);
