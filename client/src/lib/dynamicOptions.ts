/**
 * Which value a loader-driven field should switch to once its options
 * arrive, or `undefined` to keep the one it has.
 *
 * - An empty field takes the first option.
 * - A field whose options depend on another field (`loadOptionsDependsOn`)
 *   also moves to the first option when that field has just changed and the
 *   current value is not among the new options: the old value belongs to the
 *   previous list, such as a model the newly chosen endpoint does not serve.
 * - Otherwise the value stays, including on first load, so a stored value the
 *   list does not show (an alternate form, an imported workflow) is never
 *   rewritten just by opening the panel. An expression (`{{node.field}}`)
 *   always stays: it resolves at run time.
 */
export function nextDynamicOptionValue(
  currentValue: unknown,
  options: ReadonlyArray<{ value: unknown }>,
  dependencyChanged: boolean,
): unknown | undefined {
  if (options.length === 0) return undefined;
  if (currentValue === undefined || currentValue === null || currentValue === '') return options[0].value;
  if (!dependencyChanged) return undefined;
  if (typeof currentValue === 'string' && currentValue.includes('{{')) return undefined;
  return options.some((option) => option.value === currentValue) ? undefined : options[0].value;
}
