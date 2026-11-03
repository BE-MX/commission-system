export type SeedProduct = {
  name: string;
  material: string;
  length: string;
  color: string;
  retailPrice: number;
  priceA: number;
  priceB: number;
  minLevel: "retail" | "a" | "b";
  stock: number;
  status: "active" | "draft";
  tone: string;
  category: string;
  sku: string;
  construction: string;
  hairVolume: string;
  parting: string;
  craft: string;
  description: string;
  highlights: string[];
  audience: string[];
  scenarios: string[];
  images: string[];
  videoUrl: string;
};

const media = (slug: string, imageCount = 4, hasVideo = true) => ({
  images: Array.from({ length: imageCount }, (_, index) => `/products/${slug}/${String(index + 1).padStart(2, "0")}.jpg`),
  videoUrl: hasVideo ? `/products/${slug}/video.mp4` : "",
});

export const featuredProducts: SeedProduct[] = [
  {
    name: "25厘米侧分直发", material: "保鳞发", length: "25厘米", color: "自然色",
    retailPrice: 6298, priceA: 2198, priceB: 1998, minLevel: "retail", stock: 30,
    status: "active", tone: "charcoal", category: "气质系列", sku: "LS-25-SIDE",
    construction: "递针顶", hairVolume: "常规款", parting: "左分，可调整中分/侧分",
    craft: "整个头顶采用仿真头皮递针工艺，可灵活调整分缝，视觉自然，工艺细致。",
    description: "黑色顺直发丝落在锁骨位置，轻盈刘海配合流畅侧线，既有中长发的温柔，也保留日常打理的便利。",
    highlights: ["锁骨长度兼顾修饰度与轻盈感", "轻盈刘海柔化额头与脸部比例", "顺直轮廓干净百搭"],
    audience: ["偏爱自然黑直发与温柔气质", "第一次尝试中长发", "希望兼顾通勤与约会造型"],
    scenarios: ["通勤", "约会", "日常出行"], ...media("25cm-collarbone"),
  },
  {
    name: "35厘米长直发", material: "保鳞发", length: "35厘米", color: "自然色",
    retailPrice: 6598, priceA: 2298, priceB: 2098, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "臻藏系列", sku: "LS-35-LONG",
    construction: "递针左分", hairVolume: "常规款", parting: "左分",
    craft: "分缝位置采用仿真头皮递针工艺，兼顾自然效果、轻薄透气与性价比。",
    description: "经典黑长直延伸至胸前，发丝顺滑、纵向线条清晰，轻盈刘海平衡长发量感。",
    highlights: ["35厘米长发轮廓辨识度高", "纵向线条拉长整体比例", "轻盈刘海平衡长发厚重感"],
    audience: ["喜欢经典长直发与校园感", "希望通过侧面纵向线条修饰脸型", "追求明显长发长度"],
    scenarios: ["通勤", "校园", "聚会"], ...media("35cm-long-straight"),
  },
  {
    name: "一刀切-蓝黑", material: "保鳞发", length: "25厘米", color: "蓝黑色",
    retailPrice: 6298, priceA: 2198, priceB: 1998, minLevel: "retail", stock: 30,
    status: "active", tone: "charcoal", category: "气质系列", sku: "LS-BLUNT-25",
    construction: "递针顶", hairVolume: "常规款", parting: "刘海造型，顶部可中分",
    craft: "整个头顶仿真头皮，可调整中分或侧分，线条清晰且自然度高。",
    description: "蓝黑色直发波波配合齐整发尾与利落刘海，几何轮廓鲜明，呈现简约、冷感的时尚气质。",
    highlights: ["齐刘海与齐整发尾形成高辨识轮廓", "蓝黑光泽提升镜头表现", "下颌附近线条突出脸部中心"],
    audience: ["偏爱极简与冷感风格", "需要刘海修饰额头", "接受明确几何线条"],
    scenarios: ["通勤", "约会", "时尚街拍"], ...media("blunt-bob"),
  },
  {
    name: "完全挂耳波波", material: "保鳞发", length: "15厘米", color: "自然色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "安心系列", sku: "LS-EAR-BOB",
    construction: "递针旋", hairVolume: "常规款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、逼真自然，适合带刘海的不分缝造型。",
    description: "短款圆润波波完整露出耳部，轻盈刘海与贴面层次结合，后颈线条干净，整体清爽灵动。",
    highlights: ["挂耳轮廓让颈部更清晰", "圆润外形兼顾柔和与利落", "轻盈刘海减少厚重感"],
    audience: ["喜欢短波波与小巧轮廓", "希望突出脸部和颈部线条", "追求清爽易打理"],
    scenarios: ["通勤", "运动休闲", "夏日出行"], ...media("ear-tuck-bob"),
  },
  {
    name: "小清新", material: "保鳞发", length: "20厘米", color: "自然色",
    retailPrice: 5198, priceA: 1798, priceB: 1648, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "安心系列", sku: "LS-FRESH-BOB",
    construction: "递针顶", hairVolume: "常规款", parting: "刘海造型，顶部可中分",
    craft: "整个头顶仿真头皮，可灵活调整分缝，兼顾自然度与多种造型可能。",
    description: "自然黑圆润短波波搭配轻盈刘海与内扣发尾，包裹脸侧，呈现年轻、安静、亲和的清新感。",
    highlights: ["圆润内扣轮廓温柔减龄", "刘海与脸侧短层次修饰额头和颧骨", "轻巧长度适合简洁日常穿搭"],
    audience: ["喜欢温柔清新与低攻击感", "想要短波波但不喜欢硬朗齐线", "重视脸侧修饰"],
    scenarios: ["日常", "约会", "轻聚会"], ...media("fresh-bob"),
  },
  {
    name: "胎毛波波", material: "保鳞发", length: "20厘米", color: "自然色",
    retailPrice: 5198, priceA: 1798, priceB: 1648, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "安心系列", sku: "LS-BABY-BOB",
    construction: "递针顶", hairVolume: "常规款", parting: "自然左分，可调整中分/侧分",
    craft: "整个头顶仿真头皮，可自由调整分缝，细节自然，适合多种职业与日常造型。",
    description: "自然侧分的顺滑齐颌波波，没有厚重整齐刘海，贴面弧线细致，整体简约、成熟而干净。",
    highlights: ["自然侧分露出额头，成熟利落", "顺滑贴面弧线强调下颌与颈部", "无厚刘海设计适配更多正式场合"],
    audience: ["喜欢极简波波与自然侧分", "希望露出额头并柔化脸部弧线", "偏爱职业感造型"],
    scenarios: ["职场", "面试", "通勤"], ...media("baby-hair-bob"),
  },
  {
    name: "6010-B", material: "保鳞发", length: "15厘米", color: "深棕+挑蓝",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "charcoal", category: "臻藏系列", sku: "LS-6010-B",
    construction: "递针旋", hairVolume: "常规款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、逼真自然，适合带刘海的不分缝短发。",
    description: "极短精灵发以深棕为底，融入克制的蓝紫光泽，侧扫刘海、蓬松顶部与短后颈共同形成个性轮廓。",
    highlights: ["深蓝棕色调低调但有辨识度", "轻巧短轮廓突出颈部与五官", "侧刘海与圆润顶部平衡利落感"],
    audience: ["偏爱短发与街头个性", "希望减轻长发负担", "接受鲜明短发轮廓"],
    scenarios: ["旅行", "街拍", "个性日常"], ...media("6010-b"),
  },
  {
    name: "8001-A", material: "保鳞发", length: "15厘米", color: "棕色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "chestnut", category: "臻藏系列", sku: "LS-8001-A",
    construction: "递针旋", hairVolume: "轻薄款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、自然逼真，适合带刘海的不分缝造型。",
    description: "深棕色短发以侧扫纹理刘海为视觉重点，顶部松弛、鬓角与后颈干净，利落中保留柔和感。",
    highlights: ["侧向纹理聚焦眉眼", "蓬松顶部与短后颈优化比例", "短而不贴，干净又柔和"],
    audience: ["喜欢利落短发但需要顶部蓬松", "高频通勤或旅行", "希望视觉更清爽"],
    scenarios: ["通勤", "旅行", "轻商务"], ...media("8001-a"),
  },
  {
    name: "8003自然色", material: "保鳞发", length: "15厘米", color: "自然色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "气质系列", sku: "LS-8003",
    construction: "递针旋", hairVolume: "轻薄款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、自然逼真，适合简洁短刘海造型。",
    description: "紧凑黑色精灵短发搭配短刘海、圆润顶部和干净鬓角后颈，呈现极简、轻负担的活力气质。",
    highlights: ["紧凑轮廓突出五官与颈部", "适度顶部量感避免贴头皮", "干净鬓角与后颈更显精神"],
    audience: ["喜欢极简和运动休闲风", "想要干练短发", "不追求夸张纹理或颜色"],
    scenarios: ["通勤", "运动休闲", "日常"], ...media("8003", 3),
  },
  {
    name: "9005自然色", material: "保鳞发", length: "15厘米", color: "自然色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "honey", category: "气质系列", sku: "LS-9005",
    construction: "递针旋", hairVolume: "轻薄款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、自然逼真，适合带刘海的柔软短卷造型。",
    description: "暖棕短卷在头顶与两侧形成细软纹理，轻盈刘海配合圆润轮廓，亲和、灵动且有造型感。",
    highlights: ["暖棕与柔卷提升亲和力", "松软纹理让顶部更饱满", "短长度与卷度兼顾日常和造型感"],
    audience: ["喜欢温暖柔和的短卷", "希望顶部更饱满", "想柔化偏硬的脸部线条"],
    scenarios: ["聚会", "轻通勤", "拍照"], ...media("9005"),
  },
  {
    name: "主持人纹理-棕", material: "保鳞发", length: "15厘米", color: "深棕色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "chestnut", category: "高光系列", sku: "LS-HOST-TEXTURE",
    construction: "递针旋", hairVolume: "轻薄款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、自然逼真，适合镜头前整齐有序的短发造型。",
    description: "暖栗色短发带轻柔波纹，侧扫刘海与收拢顶部让纹理有序，在镜头前专业但不僵硬。",
    highlights: ["纹理清晰而不凌乱", "暖栗色柔化职业造型的硬度", "短刘海与轮廓突出眉眼和表情"],
    audience: ["主持、演讲或商务展示人群", "喜欢整齐短发和柔和可信气质", "需要镜头表现力"],
    scenarios: ["职场", "主持出镜", "商务活动"], ...media("presenter-texture"),
  },
  {
    name: "6201锡纸烫", material: "保鳞发", length: "15厘米", color: "深棕色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "charcoal", category: "高光系列", sku: "LS-6201",
    construction: "递针旋", hairVolume: "轻薄款", parting: "有刘海，不分缝",
    craft: "头顶仿真头旋，轻薄透气、自然逼真，适合层次分明的短发纹理。",
    description: "深色短发呈现分束、上扬的锡纸烫纹理，轻盈刘海配合蓬起头顶和短后颈，立体且富有态度。",
    highlights: ["分束纹理形成鲜明光影", "蓬起顶部与收紧两侧增强立体度", "不规则短纹理更年轻有个性"],
    audience: ["偏爱街头、派对或创意风格", "希望增加头顶蓬松感", "接受明显纹理"],
    scenarios: ["街头", "派对", "个性出行"], ...media("foil-perm"),
  },
  {
    name: "6010时尚款", material: "保鳞发", length: "15厘米", color: "深棕色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "espresso", category: "安心系列", sku: "LS-6010-FASHION",
    construction: "递针旋", hairVolume: "轻薄款", parting: "轻盈刘海，不分缝",
    craft: "头顶采用仿真头旋工艺，轮廓轻巧、贴合自然，适合日常高频佩戴。",
    description: "深棕色轻巧短发搭配自然碎刘海，顶部圆润、两侧贴合，整体清爽亲和，第一次佩戴也容易驾驭。",
    highlights: ["轻巧短轮廓自然百搭", "碎刘海柔化额头线条", "贴合两侧便于日常打理"],
    audience: ["第一次尝试短发假发", "喜欢自然低调造型", "重视轻便与易打理"],
    scenarios: ["日常", "通勤", "休闲出行"], ...media("6010-fashion", 4, false),
  },
  {
    name: "6010自然色", material: "保鳞发", length: "15厘米", color: "自然色",
    retailPrice: 3498, priceA: 1198, priceB: 1098, minLevel: "retail", stock: 30,
    status: "active", tone: "charcoal", category: "臻藏系列", sku: "LS-6010-NATURAL",
    construction: "递针旋", hairVolume: "轻薄款", parting: "不对称侧分刘海",
    craft: "依据脸型呈现不对称侧分与精细收边，头顶仿真头旋兼顾自然度和专属感。",
    description: "自然色不对称短发以流畅侧刘海为重点，轮廓克制精致，突出眉眼与脸部比例，适合高级定制造型。",
    highlights: ["不对称侧分体现设计感", "精细收边突出脸部轮廓", "自然色经典耐看"],
    audience: ["追求精致短发与专属感", "喜欢自然色经典造型", "重视脸型适配"],
    scenarios: ["商务", "正式会面", "品质日常"], ...media("6010-natural", 4, false),
  },
  {
    name: "果阳雪棕", material: "保鳞发", length: "40厘米", color: "雪棕色",
    retailPrice: 6998, priceA: 2398, priceB: 2198, minLevel: "retail", stock: 20,
    status: "active", tone: "honey", category: "高光系列", sku: "LS-SNOW-BROWN",
    construction: "递针中分", hairVolume: "常规款", parting: "中分空气刘海",
    craft: "中分区域采用仿真头皮递针工艺，长发层次与柔和卷度兼顾镜头表现和自然流动感。",
    description: "雪棕色长发以柔和层次和自然大弧度落在胸前，轻盈中分刘海提亮面部，适合重要社交与宴会场合。",
    highlights: ["雪棕色提升精致度与柔和感", "长层次与大弧度镜头表现突出", "中分刘海修饰颧骨与脸型"],
    audience: ["喜欢温柔长发与浅棕色调", "需要宴会或拍摄造型", "希望提升女性魅力与精致感"],
    scenarios: ["宴会", "婚礼", "重要社交"], ...media("snow-brown-long", 4, false),
  },
  {
    name: "9303深棕", material: "保鳞发", length: "45厘米", color: "深棕色",
    retailPrice: 7298, priceA: 2498, priceB: 2298, minLevel: "retail", stock: 20,
    status: "active", tone: "espresso", category: "高光系列", sku: "LS-9303",
    construction: "递针侧分", hairVolume: "丰盈款", parting: "可选单边或双边造型",
    craft: "仿真头皮分缝结合长卷层次，可呈现单边或双边两种正面效果，满足不同重要场合的造型需求。",
    description: "深棕色长卷发层次丰盈、弧度华丽，可切换单边与双边造型，呈现稳定而有仪式感的高光形象。",
    highlights: ["单边与双边两种造型可选", "丰盈长卷带来明显仪式感", "深棕色稳重上镜"],
    audience: ["参加婚礼、晚宴或庆典", "需要丰盈长卷与强镜头表现", "偏爱优雅华丽造型"],
    scenarios: ["婚礼", "晚宴", "庆典"], ...media("9303-deep-brown", 7, false),
  },
];
