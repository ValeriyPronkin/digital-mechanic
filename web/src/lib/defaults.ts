/** What a first-time viewer sees, in one place. The values are Valeriy's to decide; each is one line. */
export const UI_DEFAULTS = {
  /** «Язык ответа» in the vehicle details. false: folded to one line «Язык ответа: как в вопросе · изменить»,
   *  since the answer already comes in the language of the question and the jury and the mechanics read
   *  Russian; the select opens on «изменить». true: the select is open from the start. */
  languageSwitchOpen: false,
} as const
