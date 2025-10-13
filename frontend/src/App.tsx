import { Routes, Route, Navigate } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import EditorPage from "./pages/EditorPage";
import HighlightsPage from "./pages/HighlightsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/editor/:key" element={<EditorPage />} />
      <Route path="/highlights" element={<HighlightsPage />} /> 
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}