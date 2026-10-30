/** Names of model files as people read them: without the extension, and without the prefix every file of the set
 * shares ("Northbank-MEP.ifc", "Northbank-Site.ifc" → "MEP", "Site"). Nothing here knows a demo's name. */

const EXT = /\.(ifc|step|stp)$/i;

/** The prefix every name shares, up to and including its last separator ("Northbank-"), or "" when there is none
 * worth cutting (fewer than three characters before the separator, or one file). */
export function sharedPrefix(files: string[]): string {
  const names = files.map((f) => f.replace(EXT, ""));
  if (names.length < 2) return "";
  let prefix = names[0];
  for (const n of names.slice(1)) while (!n.startsWith(prefix)) prefix = prefix.slice(0, -1);
  const cut = prefix.match(/^(.*[A-Za-z0-9])[\s_.-]/);
  return cut && cut[1].length >= 3 ? prefix.slice(0, cut[0].length) : "";
}

/** Each file's short name in its set: the extension and the shared prefix cut, never to nothing. */
export function shortNames(files: string[]): string[] {
  const prefix = sharedPrefix(files);
  return files.map((f) => {
    const name = f.replace(EXT, "");
    return name.length > prefix.length && name.startsWith(prefix) ? name.slice(prefix.length) : name;
  });
}
