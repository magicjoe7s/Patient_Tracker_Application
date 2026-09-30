-- Register the ER computer without changing the existing device identities.
-- Applied to project vykqrhuqohmpxstudtto on 2026-09-29 with user approval.
insert into icu_sync.devices (workspace_id, user_id, device_id, label)
values (
    '9e764682-24b6-4331-b1d8-219886dbe44a'::uuid,
    'b9b47057-1865-4645-bd52-79b4b990a0f7'::uuid,
    '6f74d87e-1d08-48e6-bd79-ded8356b2ac1'::uuid,
    'ER'
)
on conflict (workspace_id, device_id) do update
set label = excluded.label,
    user_id = excluded.user_id,
    revoked_at = null;

select device_id, label, user_id, revoked_at
from icu_sync.devices
where workspace_id = '9e764682-24b6-4331-b1d8-219886dbe44a'::uuid
  and device_id = '6f74d87e-1d08-48e6-bd79-ded8356b2ac1'::uuid;
