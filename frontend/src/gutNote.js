export function formatGutNote(note, homeSubject, awaySubject) {
  if (!note) return note ?? '';
  const idx = note.indexOf(',');
  if (idx === -1) return note;
  if (!homeSubject || !awaySubject) return note;
  return `${note.slice(0, idx).trim()} (${homeSubject}), ${note.slice(idx + 1).trim()} (${awaySubject})`;
}