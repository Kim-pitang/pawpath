import { Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import MapPage from './pages/MapPage';
import MyPage from './pages/MyPage';
import PetFormPage from './pages/PetFormPage';
import PetsPage from './pages/PetsPage';
import RecommendPage from './pages/RecommendPage';
import SchedulePage from './pages/SchedulePage';
import WalkPage from './pages/WalkPage';

export default function App() {
  return (
    <Routes>
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
      </Route>
    </Routes>
  );
}
