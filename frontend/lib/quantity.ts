export function parseQuantityString(qtyStr: string): { qty_needed: number; unit: string } {
  const match = (qtyStr || '').match(/^([\d.]+)\s*(.*)$/);
  if (match) {
    return { qty_needed: parseFloat(match[1]) || 1, unit: match[2].trim() || 'unit' };
  }
  return { qty_needed: 1, unit: qtyStr || 'unit' };
}

export function getMissingIngredientDefaults(name: string): { unit: string; qty: number } {
  const lower = name.toLowerCase();
  const rules: { words: string[]; unit: string; qty: number }[] = [
    { words: ['dal', 'rice', 'atta', 'flour', 'sugar', 'salt', 'oil', 'ghee', 'masala', 'powder'], unit: 'kg', qty: 0.5 },
    { words: ['milk', 'juice', 'water', 'lassi'], unit: 'L', qty: 1 },
    { words: ['leaves', 'coriander', 'methi', 'curry'], unit: 'bunch', qty: 1 },
    { words: ['egg'], unit: 'piece', qty: 6 },
  ];
  for (const rule of rules) {
    if (rule.words.some(w => lower.includes(w))) return { unit: rule.unit, qty: rule.qty };
  }
  return { unit: 'pack', qty: 1 };
}
