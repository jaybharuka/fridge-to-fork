// Ported verbatim from templates/index.html:2976-2986 (simplifyIngredientName),
// 3021-3096 (FOOD_EMOJI_MAP), 3101-3128 (getEmojiForIngredient). Pure data +
// string logic, no DOM.

// Strips filler words so the ingredient-image search query matches better
// (e.g. "fresh chopped coriander leaves" -> "coriander").
export function simplifyIngredientName(itemName: string): string {
  const stopWords = ['fresh', 'dried', 'roasted', 'grated', 'sliced', 'chopped',
    'ground', 'whole', 'raw', 'cubes', 'paste', 'powder', 'leaves', 'seeds',
    'pieces', 'extract', 'syrup', 'sweet', 'spicy', 'tangy', 'classic'];
  return itemName
    .replace(/\(.*?\)/g, '')
    .split(' ')
    .filter(w => !stopWords.includes(w.toLowerCase()) && w.length > 2)
    .join(' ')
    .trim() || itemName;
}

const FOOD_EMOJI_MAP: Record<string, string> = {
  // Dairy & Paneer
  'paneer': '🧀', 'cheese': '🧀', 'cream': '🥛', 'butter': '🧈',
  'milk': '🥛', 'yogurt': '🥛', 'curd': '🥛', 'ghee': '🧈',
  'lassi': '🥤', 'chaas': '🥤', 'raita': '🥣',

  // Vegetables
  'spinach': '🥬', 'palak': '🥬', 'tomato': '🍅', 'onion': '🧅',
  'potato': '🥔', 'aloo': '🥔', 'garlic': '🧄', 'ginger': '🫚',
  'chilli': '🌶️', 'chili': '🌶️', 'pepper': '🌶️', 'capsicum': '🫑',
  'mushroom': '🍄', 'carrot': '🥕', 'corn': '🌽', 'broccoli': '🥦',
  'cauliflower': '🥦', 'gobi': '🥦', 'pea': '🫛', 'matar': '🫛',
  'cucumber': '🥒', 'avocado': '🥑', 'eggplant': '🍆', 'baingan': '🍆',
  'bhindi': '🫛', 'okra': '🫛', 'beans': '🫘', 'rajma': '🫘',
  'chana': '🫘', 'dal': '🫘', 'lentil': '🫘', 'chickpea': '🫘',

  // Fruits
  'lemon': '🍋', 'lime': '🍋', 'mango': '🥭', 'coconut': '🥥',
  'pomegranate': '🍎', 'apple': '🍎', 'banana': '🍌',
  'strawberry': '🍓', 'blueberry': '🫐', 'cherry': '🍒',
  'pineapple': '🍍', 'orange': '🍊', 'grape': '🍇',
  'watermelon': '🍉', 'peach': '🍑', 'pear': '🍐',

  // Spices & Condiments
  'saffron': '🌸', 'turmeric': '🟡', 'cumin': '🌿', 'jeera': '🌿',
  'coriander': '🌿', 'methi': '🌿', 'fenugreek': '🌿',
  'masala': '🫙', 'spice': '🫙', 'powder': '🫙', 'paste': '🫙',
  'chutney': '🫙', 'pickle': '🫙', 'achaar': '🫙', 'sauce': '🫙',
  'salt': '🧂', 'sugar': '🍚', 'jaggery': '🟫', 'honey': '🍯',
  'oil': '🫙', 'vinegar': '🫙', 'tamarind': '🟤',

  // Grains & Breads
  'rice': '🍚', 'basmati': '🍚', 'biryani': '🍛', 'pulao': '🍛',
  'roti': '🫓', 'naan': '🫓', 'bread': '🍞', 'pav': '🍞',
  'paratha': '🫓', 'kulcha': '🫓', 'dosa': '🫓', 'idli': '⚪',
  'pasta': '🍝', 'noodle': '🍜', 'flour': '🌾', 'atta': '🌾',
  'wheat': '🌾', 'oat': '🌾', 'semolina': '🌾', 'rava': '🌾',
  'sooji': '🌾', 'poha': '🍚', 'upma': '🍚',

  // Proteins
  'chicken': '🍗', 'mutton': '🥩', 'fish': '🐟', 'prawn': '🦐',
  'egg': '🥚', 'tofu': '🟡', 'peanut': '🥜', 'cashew': '🥜',
  'almond': '🥜', 'walnut': '🥜', 'pistachio': '🥜', 'nut': '🥜',

  // Snacks & Street Food
  'samosa': '🥟', 'pakora': '🥜', 'vada': '🍩', 'bhaji': '🥬',
  'sev': '🟡', 'papad': '💿', 'chips': '🍟', 'nachos': '🌮',
  'momos': '🥟', 'dumpling': '🥟', 'spring roll': '🌯',

  // Desserts
  'kheer': '🍮', 'halwa': '🟠', 'ladoo': '🟡', 'barfi': '🟧',
  'gulab jamun': '🟤', 'rasgulla': '⚪', 'jalebi': '🟡',
  'kulfi': '🍦', 'ice cream': '🍦', 'cake': '🎂', 'cookie': '🍪',
  'chocolate': '🍫', 'sweet': '🍬', 'candy': '🍬',
  'tiramisu': '🍮', 'pudding': '🍮', 'mousse': '🍮',

  // Drinks
  'chai': '☕', 'tea': '🍵', 'coffee': '☕', 'juice': '🧃',
  'water': '💧', 'soda': '🥤', 'smoothie': '🥤', 'shake': '🥤',
  'wine': '🍷', 'beer': '🍺', 'cocktail': '🍹',

  // Meal Types
  'soup': '🍲', 'curry': '🍛', 'stew': '🫕', 'salad': '🥗',
  'sandwich': '🥪', 'burger': '🍔', 'pizza': '🍕', 'taco': '🌮',
  'wrap': '🌯', 'bowl': '🥣', 'rice bowl': '🍛',

  // Herbs & Garnish
  'mint': '🌿', 'basil': '🌿', 'parsley': '🌿', 'oregano': '🌿',
  'rosemary': '🌿', 'thyme': '🌿', 'leaf': '🌿', 'herb': '🌿',

  // Cooking Items
  'maple syrup': '🍁', 'maple': '🍁', 'syrup': '🍯',
  'jam': '🍓', 'marmalade': '🍊', 'pesto': '🫙',
  'tahini': '🫙', 'hummus': '🫙', 'mayo': '🫙',
  'ketchup': '🍅', 'mustard': '💛',
};

// Last-resort visual when neither image source can be loaded — an emoji
// matched from the ingredient name, falling back through word-level
// substring matches then category keywords.
export function getEmojiForIngredient(name: string): string {
  const lower = name.toLowerCase();

  if (FOOD_EMOJI_MAP[lower]) return FOOD_EMOJI_MAP[lower];

  let bestMatch: string | null = null;
  let bestLength = 0;
  for (const [key, emoji] of Object.entries(FOOD_EMOJI_MAP)) {
    if (lower.includes(key) && key.length > bestLength) {
      bestMatch = emoji;
      bestLength = key.length;
    }
  }
  if (bestMatch) return bestMatch;

  if (lower.includes('veg')) return '🥗';
  if (lower.includes('non-veg') || lower.includes('meat')) return '🥩';
  if (lower.includes('drink') || lower.includes('beverage')) return '🥤';
  if (lower.includes('dessert') || lower.includes('sweet')) return '🍮';
  if (lower.includes('snack')) return '🍿';
  if (lower.includes('sauce') || lower.includes('dip')) return '🫙';
  if (lower.includes('fresh')) return '🌿';
  if (lower.includes('roasted') || lower.includes('grilled')) return '🔥';
  if (lower.includes('fried')) return '🍳';
  if (lower.includes('baked')) return '🫓';

  return '🍽️';
}
