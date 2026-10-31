import { Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import MapPage from './pages/MapPage';
import MyPage from './pages/MyPage';
import NavigatePage from './pages/NavigatePage';
import PetFormPage from './pages/PetFormPage';
import PetsPage from './pages/PetsPage';
import RecommendPage from './pages/RecommendPage';
import ReportPage from './pages/ReportPage';
import SchedulePage from './pages/SchedulePage';
import WalkPage from './pages/WalkPage';

export default function App() {
  return (
    <Routes>
      {/* 길 안내는 지도를 크게 쓰기 위해 공통 메뉴 없이 전체 화면으로 띄운다. */}
      <Route path="navigate" element={<NavigatePage />} />
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
      </Route>
    </Routes>
  );
}
