import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import GpxImportPage from './pages/GpxImportPage';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import MapPage from './pages/MapPage';
import MyPage from './pages/MyPage';
import MyWalkDetailPage from './pages/MyWalkDetailPage';
import MyWalksPage from './pages/MyWalksPage';
import NavigatePage from './pages/NavigatePage';
import PetFormPage from './pages/PetFormPage';
import PetsPage from './pages/PetsPage';
import PublicWalksPage from './pages/PublicWalksPage';
import RecommendPage from './pages/RecommendPage';
import RecordPage from './pages/RecordPage';
import ReportPage from './pages/ReportPage';
import SchedulePage from './pages/SchedulePage';
import SharedWalkPage from './pages/SharedWalkPage';
import WalkPage from './pages/WalkPage';

export default function App() {
  return (
    <Routes>
      {/* 길 안내는 지도를 크게 쓰기 위해 공통 메뉴 없이 전체 화면으로 띄운다. */}
      <Route path="navigate" element={<NavigatePage />} />
      <Route path="record" element={<RecordPage />} />
      <Route path="shared/:token" element={<SharedWalkPage />} />
      <Route path="login" element={<LoginPage />} />
      <Route path="prototypes/best-times" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/duration.html" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/courses.html" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/taste.html" element={<Navigate to="/my" replace />} />
      <Route path="prototypes/time-preference.html" element={<Navigate to="/my" replace />} />
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="pets" element={<PetsPage />} />
        <Route path="pets/new" element={<PetFormPage />} />
        <Route path="pets/:petId/edit" element={<PetFormPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="recommend" element={<RecommendPage />} />
        <Route path="map" element={<MapPage />} />
        <Route path="walk" element={<WalkPage />} />
        <Route path="my" element={<MyPage />} />
        <Route path="report" element={<ReportPage />} />
        <Route path="my-walks" element={<MyWalksPage />} />
        <Route path="my-walks/import" element={<GpxImportPage />} />
        <Route path="my-walks/:walkId" element={<MyWalkDetailPage />} />
        <Route path="public-walks" element={<PublicWalksPage />} />
      </Route>
    </Routes>
  );
}
