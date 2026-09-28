-- Reviewable activation for the owner's synthetic three-device rehearsal.
-- Apply only to project vykqrhuqohmpxstudtto after owner confirmation.
-- Does not enable clinical payloads or change the desktop's sync_enabled setting.
begin;
do $$
declare
    v_owner constant uuid := 'b9b47057-1865-4645-bd52-79b4b990a0f7';
    v_workspace constant uuid := '9e764682-24b6-4331-b1d8-219886dbe44a';
begin
    if not exists (
        select 1 from auth.users where id = v_owner and email_confirmed_at is not null
    ) then
        raise exception 'The expected confirmed tracker account does not exist.';
    end if;
    if exists (
        select 1 from icu_sync.members
        where workspace_id = v_workspace and user_id <> v_owner
    ) then
        raise exception 'Workspace already belongs to another account.';
    end if;
    insert into icu_sync.workspaces(id) values (v_workspace) on conflict (id) do nothing;
    insert into icu_sync.members(workspace_id,user_id) values (v_workspace,v_owner)
        on conflict (workspace_id,user_id) do nothing;
    if exists (
        select 1 from icu_sync.devices where workspace_id=v_workspace
        and device_id in ('40156dd8-fd58-4db3-afb2-430f35523567'::uuid,
                         '8b23052d-f9c9-4144-9d7e-a8a63c6aec84'::uuid,
                         '67a37659-d490-4432-96f8-66ab5e345b9b'::uuid)
        and (user_id <> v_owner or revoked_at is not null)
    ) then
        raise exception 'An expected device has a different owner or was revoked.';
    end if;
    insert into icu_sync.devices(workspace_id,user_id,device_id,label) values
        (v_workspace,v_owner,'40156dd8-fd58-4db3-afb2-430f35523567','Laptop'),
        (v_workspace,v_owner,'8b23052d-f9c9-4144-9d7e-a8a63c6aec84','Work computer'),
        (v_workspace,v_owner,'67a37659-d490-4432-96f8-66ab5e345b9b','Desktop')
        on conflict (workspace_id,device_id) do nothing;
end;
$$;

-- Authenticated sessions may call the RPC, but each call still checks this
-- private membership/device registry. Other accounts cannot access this workspace.
grant execute on function public.icu_sync_push(jsonb) to authenticated;
grant execute on function public.icu_sync_pull(uuid,uuid,bigint,integer) to authenticated;
revoke all on function public.icu_sync_push(jsonb) from public, anon;
revoke all on function public.icu_sync_pull(uuid,uuid,bigint,integer) from public, anon;
comment on schema icu_sync is 'ICU sync v1: authorized owner, synthetic payloads only';
notify pgrst, 'reload schema';
commit;

select
    (select count(*) from icu_sync.members where workspace_id =
        '9e764682-24b6-4331-b1d8-219886dbe44a') as authorized_accounts,
    (select count(*) from icu_sync.devices where workspace_id =
        '9e764682-24b6-4331-b1d8-219886dbe44a' and revoked_at is null) as registered_devices,
    has_function_privilege('anon','public.icu_sync_push(jsonb)','EXECUTE') as anonymous_access;
