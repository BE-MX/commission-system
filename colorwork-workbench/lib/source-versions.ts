import type { InitialCard, StockColor, TemplateSummary } from '@/lib/catalog';
import type { InventoryStatus } from '@/lib/inventory';

export type SourceVersionStatus =
  | 'uploading'
  | 'parsing'
  | 'needs_review'
  | 'ready'
  | 'active'
  | 'superseded'
  | 'failed';

export type SourceParseIssue = {
  issueId?: string;
  code: string;
  message: string;
  candidateId?: string;
  blocking: boolean;
  details?: SourceIssueDetails;
};

export type SourceIssueDetails = {
  layerCount?: number;
  layerNames?: string[];
  structureTypes?: string[];
  swatchStatus?: '待确认／待补充色块图';
};

export type SourceCard = InitialCard & {
  candidateId: string;
  geometry: NonNullable<InitialCard['geometry']>;
  matchState: 'exact' | 'new' | 'unresolved';
  matchedEntryId: string | null;
  matchReason: string;
};

export type SourceTemplateConfig = {
  schemaVersion: 1;
  template: Omit<TemplateSummary, 'initialCards'> & { initialCards: SourceCard[] };
  colors: StockColor[];
  availableLengths: number[];
  parseIssues: SourceParseIssue[];
  parseSummary: {
    layerCount: number;
    parsedColorCount: number;
    parsedSpecCount: number;
    sectionCount: number;
    documentWidth: number;
    documentHeight: number;
  };
};

export type SourceChangeItem = {
  candidateId?: string;
  entryId?: string;
  colorCode: string;
  section: string | null;
  lengths: number[];
};

export type SourceResizedItem = SourceChangeItem & {
  previousLengths: number[];
  nextLengths: number[];
};

export type SourceChangeSummary = {
  added: SourceChangeItem[];
  removed: SourceChangeItem[];
  addedLengths: SourceChangeItem[];
  removedLengths: SourceChangeItem[];
  unchanged: SourceChangeItem[];
  resized: SourceResizedItem[];
  reordered: SourceChangeItem[];
  resectioned: SourceChangeItem[];
  dimensionsChanged: {
    before: { width: number; height: number };
    after: { width: number; height: number };
  } | null;
  sectionsChanged: boolean;
  backgroundChanged: 'unknown';
};

export type SourceVersionSummary = {
  id: string;
  templateId: string;
  number: number;
  basedOnSourceVersionId: string | null;
  comparedMasterVersionId: string | null;
  status: SourceVersionStatus;
  psdName: string;
  jpgName: string;
  psdSize: number;
  jpgSize: number;
  createdBy: { id: string; email: string; displayName: string };
  createdAt: string;
  updatedAt: string;
  activatedAt: string | null;
  failureReason: string | null;
  unresolvedCount: number;
  diff: SourceChangeSummary | null;
  config?: SourceTemplateConfig | null;
};

export type SourceMappingDecision = {
  candidateId: string;
  entryId: string | null;
  treatAsNew: boolean;
  ignore?: boolean;
  lengths: number[];
  section: string | null;
};

export type SourceInitialStatus = {
  candidateId: string;
  length: number;
  status: InventoryStatus;
};

export function sourceAssetUrl(sourceVersionId: string, assetName: string) {
  return `/api/template-source-assets/${encodeURIComponent(sourceVersionId)}/${assetName
    .split('/')
    .map(encodeURIComponent)
    .join('/')}`;
}

function issueHash(value: string) {
  let current = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    current ^= value.charCodeAt(index);
    current = Math.imul(current, 16777619);
  }
  return (current >>> 0).toString(36);
}

export function sourceIssueKey(issue: SourceParseIssue) {
  return issue.issueId || `${issue.code}:${issue.candidateId || issueHash(issue.message)}`;
}
