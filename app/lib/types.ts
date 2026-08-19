export type LevelCode = "retail" | "a" | "b";

export type Product = {
  id: number; name: string; material: string; length: string; color: string;
  retailPrice: number; priceA: number; priceB: number; minLevel: LevelCode;
  stock: number; status: "active" | "draft"; tone: string; createdAt: string;
};

export type WholesaleLevel = {
  id: number; code: LevelCode; name: string; threshold: number; rank: number;
};
