"""처음 구조. Alembic을 들이기 전 app.migrations.ensure_schema가 만들던 구조와 같다.

Alembic 이전에 만든 DB는 이 리비전을 실행하지 않고 app.migrations가 이 구조로 맞춘 뒤 0001로 표시한다.
되돌리면(downgrade) 모든 테이블과 데이터가 지워진다. 빈 DB에서만 쓰세요.

Revision ID: 0001
Revises:
Create Date: 2026-11-01 02:04:11.721979

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('oauth_states',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('state_hash', sa.String(length=64), nullable=False),
    sa.Column('nonce', sa.String(length=100), nullable=False),
    sa.Column('code_verifier', sa.String(length=128), nullable=False),
    sa.Column('next_path', sa.String(length=300), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('reauth_user_id', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('state_hash')
    )
    op.create_index(op.f('ix_oauth_states_expires_at'), 'oauth_states', ['expires_at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('available_windows', sa.JSON(), nullable=False),
    sa.Column('preferred_duration_min', sa.Integer(), nullable=False),
    sa.Column('walks_per_day', sa.Integer(), nullable=False),
    sa.Column('login_id', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('password_hash', sa.String(length=200), nullable=True),
    sa.Column('google_sub', sa.String(length=64), nullable=True),
    sa.Column('google_email', sa.String(length=254), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_google_sub'), 'users', ['google_sub'], unique=True)
    op.create_index(op.f('ix_users_login_id'), 'users', ['login_id'], unique=True)
    op.create_table('weather_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('forecast_time', sa.DateTime(), nullable=False),
    sa.Column('temperature', sa.Float(), nullable=False),
    sa.Column('apparent_temperature', sa.Float(), nullable=False),
    sa.Column('precipitation_probability', sa.Float(), nullable=False),
    sa.Column('precipitation_mm', sa.Float(), nullable=False),
    sa.Column('humidity', sa.Float(), nullable=False),
    sa.Column('wind_speed', sa.Float(), nullable=False),
    sa.Column('uv_index', sa.Float(), nullable=True),
    sa.Column('is_day', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'forecast_time', name='uq_weather_source_time')
    )
    op.create_index(op.f('ix_weather_records_forecast_time'), 'weather_records', ['forecast_time'], unique=False)
    op.create_index(op.f('ix_weather_records_source'), 'weather_records', ['source'], unique=False)
    op.create_table('pets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('breed', sa.String(length=50), nullable=False),
    sa.Column('age_years', sa.Float(), nullable=False),
    sa.Column('weight_kg', sa.Float(), nullable=False),
    sa.Column('size', sa.String(length=10), nullable=False),
    sa.Column('activity_level', sa.String(length=10), nullable=False),
    sa.Column('personality', sa.String(length=10), nullable=False),
    sa.Column('path_preference', sa.String(length=10), nullable=False),
    sa.Column('heat_sensitivity', sa.String(length=10), nullable=False),
    sa.Column('novelty_reaction', sa.String(length=10), nullable=False),
    sa.Column('preferred_distance_km', sa.Float(), nullable=True),
    sa.Column('preferred_time_bucket', sa.String(length=10), nullable=True),
    sa.Column('learned_attribute_weights', sa.JSON(), nullable=False),
    sa.Column('learned_time_buckets', sa.JSON(), nullable=False),
    sa.Column('feedback_total', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pets_user_id'), 'pets', ['user_id'], unique=False)
    op.create_table('profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=30), nullable=False),
    sa.Column('avatar_key', sa.String(length=20), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('available_windows', sa.JSON(), nullable=False),
    sa.Column('preferred_duration_min', sa.Integer(), nullable=False),
    sa.Column('walks_per_day', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('last_active_at', sa.DateTime(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_profiles_user_id'), 'profiles', ['user_id'], unique=False)
    op.create_index('ux_profiles_one_default', 'profiles', ['user_id'], unique=True, sqlite_where=sa.text('is_default'), postgresql_where=sa.text('is_default'))
    op.create_table('auth_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=True),
    sa.Column('reauthenticated_at', sa.DateTime(), nullable=True),
    sa.Column('profile_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_auth_sessions_expires_at'), 'auth_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_auth_sessions_profile_id'), 'auth_sessions', ['profile_id'], unique=False)
    op.create_index(op.f('ix_auth_sessions_user_id'), 'auth_sessions', ['user_id'], unique=False)
    op.create_table('saved_walks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=True),
    sa.Column('pet_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=80), nullable=False),
    sa.Column('memo', sa.Text(), nullable=False),
    sa.Column('source_type', sa.String(length=10), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('duration_sec', sa.Integer(), nullable=True),
    sa.Column('average_speed_mps', sa.Float(), nullable=True),
    sa.Column('has_timestamps', sa.Boolean(), nullable=False),
    sa.Column('point_count', sa.Integer(), nullable=False),
    sa.Column('visibility', sa.String(length=10), nullable=False),
    sa.Column('share_token', sa.String(length=64), nullable=True),
    sa.Column('share_expires_at', sa.DateTime(), nullable=True),
    sa.Column('share_memo', sa.Boolean(), nullable=False),
    sa.Column('client_id', sa.String(length=64), nullable=True),
    sa.Column('route_hash', sa.String(length=64), nullable=False),
    sa.Column('preview', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_id'),
    sa.UniqueConstraint('share_token')
    )
    op.create_index(op.f('ix_saved_walks_pet_id'), 'saved_walks', ['pet_id'], unique=False)
    op.create_index(op.f('ix_saved_walks_profile_id'), 'saved_walks', ['profile_id'], unique=False)
    op.create_index(op.f('ix_saved_walks_route_hash'), 'saved_walks', ['route_hash'], unique=False)
    op.create_index(op.f('ix_saved_walks_started_at'), 'saved_walks', ['started_at'], unique=False)
    op.create_index(op.f('ix_saved_walks_user_id'), 'saved_walks', ['user_id'], unique=False)
    op.create_table('saved_walk_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('walk_id', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['walk_id'], ['saved_walks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_saved_walk_photos_walk_id'), 'saved_walk_photos', ['walk_id'], unique=False)
    op.create_table('saved_walk_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('walk_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('segment', sa.Integer(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('altitude', sa.Float(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(), nullable=True),
    sa.Column('accuracy', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['walk_id'], ['saved_walks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_saved_walk_points_walk_sequence', 'saved_walk_points', ['walk_id', 'sequence'], unique=True)
    op.create_table('community_trails',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('saved_walk_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('cover_photo_id', sa.Integer(), nullable=True),
    sa.Column('visibility', sa.String(length=10), nullable=False),
    sa.Column('region', sa.String(length=50), nullable=False),
    sa.Column('features', sa.JSON(), nullable=False),
    sa.Column('suitable_for', sa.JSON(), nullable=False),
    sa.Column('hide_radius_m', sa.Integer(), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('estimated_min', sa.Integer(), nullable=False),
    sa.Column('elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('difficulty', sa.String(length=10), nullable=False),
    sa.Column('start_lat', sa.Float(), nullable=False),
    sa.Column('start_lng', sa.Float(), nullable=False),
    sa.Column('end_lat', sa.Float(), nullable=False),
    sa.Column('end_lng', sa.Float(), nullable=False),
    sa.Column('start_label', sa.String(length=100), nullable=True),
    sa.Column('end_label', sa.String(length=100), nullable=True),
    sa.Column('preview', sa.JSON(), nullable=False),
    sa.Column('view_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cover_photo_id'], ['saved_walk_photos.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['saved_walk_id'], ['saved_walks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('saved_walk_id')
    )
    op.create_index(op.f('ix_community_trails_difficulty'), 'community_trails', ['difficulty'], unique=False)
    op.create_index(op.f('ix_community_trails_distance_m'), 'community_trails', ['distance_m'], unique=False)
    op.create_index(op.f('ix_community_trails_estimated_min'), 'community_trails', ['estimated_min'], unique=False)
    op.create_index(op.f('ix_community_trails_region'), 'community_trails', ['region'], unique=False)
    op.create_index(op.f('ix_community_trails_user_id'), 'community_trails', ['user_id'], unique=False)
    op.create_index('ix_community_trails_visibility_created', 'community_trails', ['visibility', 'created_at'], unique=False)
    op.create_table('trail_bookmarks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('community_trail_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['community_trail_id'], ['community_trails.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'community_trail_id', name='uq_trail_bookmark_user')
    )
    op.create_index(op.f('ix_trail_bookmarks_community_trail_id'), 'trail_bookmarks', ['community_trail_id'], unique=False)
    op.create_index(op.f('ix_trail_bookmarks_user_id'), 'trail_bookmarks', ['user_id'], unique=False)
    op.create_table('trail_likes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('community_trail_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['community_trail_id'], ['community_trails.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'community_trail_id', name='uq_trail_like_user')
    )
    op.create_index(op.f('ix_trail_likes_community_trail_id'), 'trail_likes', ['community_trail_id'], unique=False)
    op.create_index(op.f('ix_trail_likes_user_id'), 'trail_likes', ['user_id'], unique=False)
    op.create_table('trail_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('community_trail_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_trail_review_rating'),
    sa.ForeignKeyConstraint(['community_trail_id'], ['community_trails.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'community_trail_id', name='uq_trail_review_user')
    )
    op.create_index(op.f('ix_trail_reviews_community_trail_id'), 'trail_reviews', ['community_trail_id'], unique=False)
    op.create_index(op.f('ix_trail_reviews_user_id'), 'trail_reviews', ['user_id'], unique=False)
    op.create_table('walking_courses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('area', sa.String(length=50), nullable=False),
    sa.Column('start_lat', sa.Float(), nullable=False),
    sa.Column('start_lng', sa.Float(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('route', sa.JSON(), nullable=False),
    sa.Column('has_park', sa.Boolean(), nullable=False),
    sa.Column('park_names', sa.JSON(), nullable=False),
    sa.Column('lighting', sa.String(length=10), nullable=False),
    sa.Column('is_paved', sa.Boolean(), nullable=False),
    sa.Column('surface_note', sa.String(length=80), nullable=False),
    sa.Column('crowd_level', sa.String(length=10), nullable=False),
    sa.Column('pet_allowed', sa.Boolean(), nullable=False),
    sa.Column('pet_rule_note', sa.String(length=120), nullable=False),
    sa.Column('facilities', sa.JSON(), nullable=False),
    sa.Column('is_familiar', sa.Boolean(), nullable=False),
    sa.Column('shade_level', sa.Float(), nullable=False),
    sa.Column('difficulty', sa.String(length=10), nullable=False),
    sa.Column('traffic_exposure', sa.String(length=10), nullable=False),
    sa.Column('scenery_tags', sa.JSON(), nullable=False),
    sa.Column('data_sources', sa.JSON(), nullable=False),
    sa.Column('environment', sa.JSON(), nullable=True),
    sa.Column('owner_user_id', sa.Integer(), nullable=True),
    sa.Column('saved_walk_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('community_trail_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['community_trail_id'], ['community_trails.id'], ),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['saved_walk_id'], ['saved_walks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_walking_courses_community_trail_id'), 'walking_courses', ['community_trail_id'], unique=True)
    op.create_index(op.f('ix_walking_courses_owner_user_id'), 'walking_courses', ['owner_user_id'], unique=False)
    op.create_table('pet_course_preferences',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('affinity', sa.Float(), nullable=False),
    sa.Column('weighted_sum', sa.Float(), nullable=False),
    sa.Column('weight_total', sa.Float(), nullable=False),
    sa.Column('visit_count', sa.Integer(), nullable=False),
    sa.Column('feedback_count', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('pet_id', 'course_id', name='uq_pet_course')
    )
    op.create_index(op.f('ix_pet_course_preferences_course_id'), 'pet_course_preferences', ['course_id'], unique=False)
    op.create_index(op.f('ix_pet_course_preferences_pet_id'), 'pet_course_preferences', ['pet_id'], unique=False)
    op.create_table('recommendations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=True),
    sa.Column('top_course_id', sa.Integer(), nullable=True),
    sa.Column('weather_record_id', sa.Integer(), nullable=True),
    sa.Column('weather_source', sa.String(length=40), nullable=False),
    sa.Column('weather_scenario', sa.String(length=20), nullable=False),
    sa.Column('walkable', sa.Boolean(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('algorithm_version', sa.String(length=20), nullable=True),
    sa.Column('weather_fetched_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.ForeignKeyConstraint(['top_course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['weather_record_id'], ['weather_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recommendations_created_at'), 'recommendations', ['created_at'], unique=False)
    op.create_index(op.f('ix_recommendations_pet_id'), 'recommendations', ['pet_id'], unique=False)
    op.create_index(op.f('ix_recommendations_profile_id'), 'recommendations', ['profile_id'], unique=False)
    op.create_table('trail_review_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('review_id', sa.Integer(), nullable=False),
    sa.Column('content_type', sa.String(length=20), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['trail_reviews.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trail_review_photos_review_id'), 'trail_review_photos', ['review_id'], unique=False)
    op.create_table('recommendation_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recommendation_id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('event', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('recommendation_id', 'course_id', 'event', name='uq_recommendation_event')
    )
    op.create_index(op.f('ix_recommendation_events_pet_id'), 'recommendation_events', ['pet_id'], unique=False)
    op.create_index(op.f('ix_recommendation_events_recommendation_id'), 'recommendation_events', ['recommendation_id'], unique=False)
    op.create_table('recommendation_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recommendation_id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('algorithm_version', sa.String(length=20), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=True),
    sa.Column('total_score', sa.Float(), nullable=True),
    sa.Column('personalization_score', sa.Float(), nullable=True),
    sa.Column('safety_penalty', sa.Float(), nullable=False),
    sa.Column('skip_penalty', sa.Float(), nullable=False),
    sa.Column('safety_level', sa.String(length=10), nullable=True),
    sa.Column('safety_score', sa.Float(), nullable=True),
    sa.Column('group_scores', sa.JSON(), nullable=False),
    sa.Column('data_quality', sa.JSON(), nullable=False),
    sa.Column('excluded_reasons', sa.JSON(), nullable=False),
    sa.Column('duplicate_of', sa.Integer(), nullable=True),
    sa.Column('exploration', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('recommendation_id', 'course_id', name='uq_recommendation_item_course')
    )
    op.create_index(op.f('ix_recommendation_items_course_id'), 'recommendation_items', ['course_id'], unique=False)
    op.create_index(op.f('ix_recommendation_items_pet_id'), 'recommendation_items', ['pet_id'], unique=False)
    op.create_index(op.f('ix_recommendation_items_recommendation_id'), 'recommendation_items', ['recommendation_id'], unique=False)
    op.create_table('walk_histories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=True),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('recommendation_id', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('tracking_source', sa.String(length=12), nullable=True),
    sa.Column('distance_km', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_walk_histories_course_id'), 'walk_histories', ['course_id'], unique=False)
    op.create_index(op.f('ix_walk_histories_pet_id'), 'walk_histories', ['pet_id'], unique=False)
    op.create_index(op.f('ix_walk_histories_profile_id'), 'walk_histories', ['profile_id'], unique=False)
    op.create_table('walk_feedbacks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('walk_id', sa.Integer(), nullable=False),
    sa.Column('pet_id', sa.Integer(), nullable=False),
    sa.Column('profile_id', sa.Integer(), nullable=True),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('walk_rating', sa.Integer(), nullable=False),
    sa.Column('pet_rating', sa.Integer(), nullable=False),
    sa.Column('difficulty', sa.String(length=10), nullable=False),
    sa.Column('weather_rating', sa.Integer(), nullable=False),
    sa.Column('would_revisit', sa.Boolean(), nullable=False),
    sa.Column('memo', sa.Text(), nullable=False),
    sa.Column('signal', sa.Float(), nullable=False),
    sa.Column('affinity_before', sa.Float(), nullable=False),
    sa.Column('affinity_after', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['walking_courses.id'], ),
    sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ),
    sa.ForeignKeyConstraint(['profile_id'], ['profiles.id'], ),
    sa.ForeignKeyConstraint(['walk_id'], ['walk_histories.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('walk_id')
    )
    op.create_index(op.f('ix_walk_feedbacks_course_id'), 'walk_feedbacks', ['course_id'], unique=False)
    op.create_index(op.f('ix_walk_feedbacks_pet_id'), 'walk_feedbacks', ['pet_id'], unique=False)
    op.create_index(op.f('ix_walk_feedbacks_profile_id'), 'walk_feedbacks', ['profile_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_walk_feedbacks_profile_id'), table_name='walk_feedbacks')
    op.drop_index(op.f('ix_walk_feedbacks_pet_id'), table_name='walk_feedbacks')
    op.drop_index(op.f('ix_walk_feedbacks_course_id'), table_name='walk_feedbacks')
    op.drop_table('walk_feedbacks')
    op.drop_index(op.f('ix_walk_histories_profile_id'), table_name='walk_histories')
    op.drop_index(op.f('ix_walk_histories_pet_id'), table_name='walk_histories')
    op.drop_index(op.f('ix_walk_histories_course_id'), table_name='walk_histories')
    op.drop_table('walk_histories')
    op.drop_index(op.f('ix_recommendation_items_recommendation_id'), table_name='recommendation_items')
    op.drop_index(op.f('ix_recommendation_items_pet_id'), table_name='recommendation_items')
    op.drop_index(op.f('ix_recommendation_items_course_id'), table_name='recommendation_items')
    op.drop_table('recommendation_items')
    op.drop_index(op.f('ix_recommendation_events_recommendation_id'), table_name='recommendation_events')
    op.drop_index(op.f('ix_recommendation_events_pet_id'), table_name='recommendation_events')
    op.drop_table('recommendation_events')
    op.drop_index(op.f('ix_trail_review_photos_review_id'), table_name='trail_review_photos')
    op.drop_table('trail_review_photos')
    op.drop_index(op.f('ix_recommendations_profile_id'), table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_pet_id'), table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_created_at'), table_name='recommendations')
    op.drop_table('recommendations')
    op.drop_index(op.f('ix_pet_course_preferences_pet_id'), table_name='pet_course_preferences')
    op.drop_index(op.f('ix_pet_course_preferences_course_id'), table_name='pet_course_preferences')
    op.drop_table('pet_course_preferences')
    op.drop_index(op.f('ix_walking_courses_owner_user_id'), table_name='walking_courses')
    op.drop_index(op.f('ix_walking_courses_community_trail_id'), table_name='walking_courses')
    op.drop_table('walking_courses')
    op.drop_index(op.f('ix_trail_reviews_user_id'), table_name='trail_reviews')
    op.drop_index(op.f('ix_trail_reviews_community_trail_id'), table_name='trail_reviews')
    op.drop_table('trail_reviews')
    op.drop_index(op.f('ix_trail_likes_user_id'), table_name='trail_likes')
    op.drop_index(op.f('ix_trail_likes_community_trail_id'), table_name='trail_likes')
    op.drop_table('trail_likes')
    op.drop_index(op.f('ix_trail_bookmarks_user_id'), table_name='trail_bookmarks')
    op.drop_index(op.f('ix_trail_bookmarks_community_trail_id'), table_name='trail_bookmarks')
    op.drop_table('trail_bookmarks')
    op.drop_index('ix_community_trails_visibility_created', table_name='community_trails')
    op.drop_index(op.f('ix_community_trails_user_id'), table_name='community_trails')
    op.drop_index(op.f('ix_community_trails_region'), table_name='community_trails')
    op.drop_index(op.f('ix_community_trails_estimated_min'), table_name='community_trails')
    op.drop_index(op.f('ix_community_trails_distance_m'), table_name='community_trails')
    op.drop_index(op.f('ix_community_trails_difficulty'), table_name='community_trails')
    op.drop_table('community_trails')
    op.drop_index('ix_saved_walk_points_walk_sequence', table_name='saved_walk_points')
    op.drop_table('saved_walk_points')
    op.drop_index(op.f('ix_saved_walk_photos_walk_id'), table_name='saved_walk_photos')
    op.drop_table('saved_walk_photos')
    op.drop_index(op.f('ix_saved_walks_user_id'), table_name='saved_walks')
    op.drop_index(op.f('ix_saved_walks_started_at'), table_name='saved_walks')
    op.drop_index(op.f('ix_saved_walks_route_hash'), table_name='saved_walks')
    op.drop_index(op.f('ix_saved_walks_profile_id'), table_name='saved_walks')
    op.drop_index(op.f('ix_saved_walks_pet_id'), table_name='saved_walks')
    op.drop_table('saved_walks')
    op.drop_index(op.f('ix_auth_sessions_user_id'), table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_profile_id'), table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_expires_at'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index('ux_profiles_one_default', table_name='profiles', sqlite_where=sa.text('is_default'), postgresql_where=sa.text('is_default'))
    op.drop_index(op.f('ix_profiles_user_id'), table_name='profiles')
    op.drop_table('profiles')
    op.drop_index(op.f('ix_pets_user_id'), table_name='pets')
    op.drop_table('pets')
    op.drop_index(op.f('ix_weather_records_source'), table_name='weather_records')
    op.drop_index(op.f('ix_weather_records_forecast_time'), table_name='weather_records')
    op.drop_table('weather_records')
    op.drop_index(op.f('ix_users_login_id'), table_name='users')
    op.drop_index(op.f('ix_users_google_sub'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_oauth_states_expires_at'), table_name='oauth_states')
    op.drop_table('oauth_states')
