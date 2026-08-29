export type LevelCode = "retail" | "a" | "b";

export type Product = {
  id: number; name: string; material: string; length: string; color: string;
  retailPrice: number; priceA: number; priceB: number; minLevel: LevelCode;
  stock: number; status: "active" | "draft"; tone: string; category: string; sku: string; createdAt: string;
  construction: string; hairVolume: string; parting: string; craft: string; description: string;
  highlights: string[]; audience: string[]; scenarios: string[]; images: string[]; videoUrl: string;
};

export type WholesaleLevel = {
  id: number; code: LevelCode; name: string; threshold: number; rank: number;
};

export type WholesaleAccount = {
  id: number; companyName: string; phone: string; level: "a" | "b";
  salesPerson: string; note: string;
};

export type AccessLog = {
  id: number; companyName: string | null; phone: string; level: "a" | "b" | null;
  salesPerson: string | null; result: "success" | "failed" | "unknown"; accessAt: string;
  channel: "retail" | "wholesale";
};

export type Order = {
  id: number; orderNo: string; channel: "retail" | "wholesale"; customerPhone: string;
  customerName: string; level: LevelCode; salesPerson: string; status: string; paymentStatus: string;
  logisticsCompany: string; trackingNo: string; logisticsStatus: string; itemCount: number;
  amount: number; commissionAmount: number; createdAt: string; shippedAt: string | null;
};

export type SalesPerson = {
  id: number; name: string; phone: string; role: string; promoCode: string; storeCode: string;
  customerService: string; status: string; customerCount?: number; orderAmount?: number; commission?: number;
};

export type CustomerProfile = {
  id: number; phone: string; channel: "retail" | "wholesale"; displayName: string; storeName: string;
  level: LevelCode; salesPerson: string; customerService: string; note: string; referralCode: string;
  status: string; createdAt: string; lastLoginAt: string | null;
};

export type Promotion = {
  id: number; title: string; audience: string; benefitType: string; benefitValue: number;
  description: string; status: string; endsAt: string | null;
};
