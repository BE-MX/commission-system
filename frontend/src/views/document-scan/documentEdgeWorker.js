import { detectDocument } from './documentEdges.js'

self.onmessage = ({ data }) => self.postMessage(detectDocument(data))
