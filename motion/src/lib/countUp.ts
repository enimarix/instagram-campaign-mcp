// Numbers that count up in captions (steps 130, 131). Pure, so `node --test` runs it.

/**
 * `text` with its first number at `p` (0..1) of its value, same decimals and grouping:
 * "1,6 g" -> "0,8 g" at 0.5. Numbers count up in captions and on the phone.
 */
export const countUp = (text: string, p: number): string =>
  text.replace(/\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/, (num) => {
    const dec = /[.,](\d+)$/.exec(num);
    const whole = dec ? num.slice(0, dec.index) : num;
    const value = Number(whole.replace(/\D/g, "") + (dec ? `.${dec[1]}` : "")) * Math.min(1, Math.max(0, p));
    const [i, d] = value.toFixed(dec ? dec[1].length : 0).split(".");
    const grouped = /\D/.test(whole) ? i.replace(/\B(?=(\d{3})+$)/g, "\u00a0") : i;
    return d ? `${grouped}${num[dec!.index]}${d}` : grouped;
  });
