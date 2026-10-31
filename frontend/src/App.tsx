import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import AccountPage from './pages/AccountPage';
import CommunityPage from './pages/CommunityPage';
import GoodbyePage from './pages/GoodbyePage';
import GeneratePage from './pages/GeneratePage';
import RequireProfile from './components/RequireProfile';
import GpxImportPage from './pages/GpxImportPage';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import MapPage from './pages/MapPage';
import MyPage from './pages/MyPage';
import MyTrailsPage from './pages/MyTrailsPage';
import MyWalkDetailPage from './pages/MyWalkDetailPage';
import MyWalksPage from './pages/MyWalksPage';
import NavigatePage from './pages/NavigatePage';
import PetFormPage from './pages/PetFormPage';
import PetsPage from './pages/PetsPage';
import FamilyPage from './pages/FamilyPage';
import ProfileFormPage from './pages/ProfileFormPage';
import ProfilesPage from './pages/ProfilesPage';
import PublicWalksPage from './pages/PublicWalksPage';
import RecommendPage from './pages/RecommendPage';
import RecordPage from './pages/RecordPage';
import ReportPage from './pages/ReportPage';
import SchedulePage from './pages/SchedulePage';
import SharedWalkPage from './pages/SharedWalkPage';
import TrailDetailPage from './pages/TrailDetailPage';
import TrailSharePage from './pages/TrailSharePage';
import WalkPage from './pages/WalkPage';

export default function App() {
  return (
    <Routes>
      {/* 길 안내는 지도를 크게 쓰기 위해 공통 메뉴 없이 전체 화면으로 띄운다. */}
      <Route path="navigate" element={<RequireProfile><NavigatePage /></RequireProfile>} />
      <Route path="record" element={<RequireProfile><RecordPage /></RequireProfile>} />
      <Route path="shared/:token" element={<SharedWalkPage />} />
      <Route path="login" element={<LoginPage />} />
      <Route path="prototypes/best-times" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/duration.html" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/courses.html" element={<Navigate to="/recommend" replace />} />
      <Route path="prototypes/taste.html" element={<Navigate to="/my" replace />} />
      <Route path="prototypes/time-preference.html" element={<Navigate to="/my" replace />} />
      <Route path="goodbye" element={<GoodbyePage />} />
      {/* 프로필 선택은 넷플릭스처럼 메뉴 없이 전체 화면으로 띄운다. */}
      <Route path="profiles" element={<ProfilesPage />} />
      <Route path="profiles/new" element={<ProfileFormPage mode="new" />} />
      <Route path="profiles/setup" element={<ProfileFormPage mode="setup" />} />
      <Route path="profiles/:profileId/edit" element={<ProfileFormPage mode="edit" />} />
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
        <Route path="account" element={<AccountPage />} />
        <Route path="family" element={<FamilyPage />} />
        <Route path="report" element={<ReportPage />} />
        <Route path="my-walks" element={<MyWalksPage />} />
        <Route path="my-walks/import" element={<GpxImportPage />} />
        <Route path="generate" element={<GeneratePage />} />
        <Route path="my-walks/:walkId" element={<MyWalkDetailPage />} />
        <Route path="public-walks" element={<PublicWalksPage />} />
        <Route path="community" element={<CommunityPage />} />
        <Route path="community/share" element={<TrailSharePage />} />
        <Route path="community/my" element={<MyTrailsPage />} />
        <Route path="community/trails/:trailId" element={<TrailDetailPage />} />
        <Route path="community/trails/:trailId/edit" element={<TrailSharePage />} />
      </Route>
    </Routes>
  );
}
