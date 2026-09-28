-- ICU Patient Tracker: Supabase-native sync foundation.
-- No client access is granted by this migration. Synthetic payloads only.
begin;
create schema if not exists icu_sync;
revoke all on schema icu_sync from public, anon, authenticated;

create table if not exists icu_sync.workspaces (
    id uuid primary key,
    change_sequence bigint not null default 0 check (change_sequence >= 0)
);
create table if not exists icu_sync.members (
    workspace_id uuid not null references icu_sync.workspaces(id),
    user_id uuid not null,
    primary key (workspace_id, user_id)
);
create table if not exists icu_sync.devices (
    workspace_id uuid not null,
    user_id uuid not null,
    device_id uuid not null,
    label text not null check (length(label) between 1 and 100),
    revoked_at timestamptz,
    primary key (workspace_id, device_id),
    foreign key (workspace_id, user_id) references icu_sync.members(workspace_id, user_id)
);
create table if not exists icu_sync.entities (
    workspace_id uuid not null references icu_sync.workspaces(id),
    entity_type text not null check (entity_type = 'synthetic_patient'),
    entity_id uuid not null,
    server_version bigint not null check (server_version > 0),
    payload jsonb not null,
    deleted boolean not null,
    updated_at timestamptz not null default now(),
    primary key (workspace_id, entity_type, entity_id)
);
create table if not exists icu_sync.changes (
    workspace_id uuid not null references icu_sync.workspaces(id),
    sequence bigint not null,
    entity_type text not null,
    entity_id uuid not null,
    operation text not null check (operation in ('upsert', 'delete')),
    server_version bigint not null,
    payload jsonb not null,
    user_id uuid not null,
    device_id uuid not null,
    created_at timestamptz not null default now(),
    primary key (workspace_id, sequence)
);
create table if not exists icu_sync.receipts (
    workspace_id uuid not null references icu_sync.workspaces(id),
    operation_id uuid not null,
    request_hash bytea not null,
    response jsonb not null,
    created_at timestamptz not null default now(),
    primary key (workspace_id, operation_id)
);

alter table icu_sync.workspaces enable row level security;
alter table icu_sync.members enable row level security;
alter table icu_sync.devices enable row level security;
alter table icu_sync.entities enable row level security;
alter table icu_sync.changes enable row level security;
alter table icu_sync.receipts enable row level security;
revoke all on all tables in schema icu_sync from public, anon, authenticated;

create or replace function icu_sync.require_device(p_workspace uuid, p_device uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_user uuid := auth.uid();
begin
    if v_user is null or not exists (
        select 1 from icu_sync.devices d
        join icu_sync.members m on m.workspace_id = d.workspace_id and m.user_id = d.user_id
        where d.workspace_id = p_workspace and d.device_id = p_device
          and d.user_id = v_user and d.revoked_at is null
    ) then
        raise insufficient_privilege using message = 'Tracker device is not authorized.';
    end if;
    return v_user;
end;
$$;
revoke all on function icu_sync.require_device(uuid, uuid) from public, anon, authenticated;

create or replace function public.icu_sync_push(p_request jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_workspace uuid;
    v_device uuid;
    v_user uuid;
    v_sequence bigint;
    v_op jsonb;
    v_id uuid;
    v_entity uuid;
    v_type text;
    v_kind text;
    v_base bigint;
    v_payload jsonb;
    v_hash bytea;
    v_receipt icu_sync.receipts%rowtype;
    v_current icu_sync.entities%rowtype;
    v_version bigint;
    v_result jsonb;
    v_results jsonb := '[]'::jsonb;
begin
    if jsonb_typeof(p_request) is distinct from 'object'
       or octet_length(p_request::text) > 1048576 then
        raise invalid_parameter_value using message = 'Invalid sync request.';
    end if;
    v_workspace := (p_request->>'workspace_id')::uuid;
    v_device := (p_request->>'device_id')::uuid;
    v_user := icu_sync.require_device(v_workspace, v_device);
    if jsonb_typeof(p_request->'operations') is distinct from 'array' then
        raise invalid_parameter_value using message = 'Operations must be an array.';
    end if;
    if jsonb_array_length(p_request->'operations') > 100 then
        raise invalid_parameter_value using message = 'Too many operations.';
    end if;
    -- Hold this row lock through commit: sequence allocation follows commit order.
    select change_sequence into strict v_sequence from icu_sync.workspaces
        where id = v_workspace for update;
    for v_op in select value from jsonb_array_elements(p_request->'operations') loop
        v_id := (v_op->>'operation_id')::uuid;
        v_entity := (v_op->>'entity_id')::uuid;
        v_type := v_op->>'entity_type';
        v_kind := v_op->>'operation';
        v_payload := v_op->'payload';
        if v_id is null or v_entity is null
           or v_type is distinct from 'synthetic_patient'
           or v_kind is null or v_kind not in ('upsert', 'delete')
           or jsonb_typeof(v_payload) is distinct from 'object'
           or jsonb_typeof(v_op->'base_server_version') is distinct from 'number'
           or (v_op->>'base_server_version') !~ '^[0-9]{1,15}$' then
            raise invalid_parameter_value using message = 'Invalid synthetic operation.';
        end if;
        v_base := (v_op->>'base_server_version')::bigint;
        v_hash := sha256(convert_to(jsonb_build_object(
            'user_id', v_user, 'device_id', v_device, 'operation', v_op)::text, 'UTF8'));
        select * into v_receipt from icu_sync.receipts
            where workspace_id = v_workspace and operation_id = v_id;
        if found then
            if v_receipt.request_hash <> v_hash then
                raise invalid_parameter_value using message = 'Operation ID reused with different content.';
            end if;
            v_results := v_results || jsonb_build_array(v_receipt.response);
            continue;
        end if;
        select * into v_current from icu_sync.entities
            where workspace_id = v_workspace and entity_type = v_type and entity_id = v_entity;
        v_version := coalesce(v_current.server_version, 0);
        if v_base <> v_version then
            v_result := jsonb_build_object(
                'operation_id', v_id, 'entity_type', v_type, 'entity_id', v_entity,
                'status', 'conflict', 'server_version', v_version,
                'change_sequence', null, 'server_payload', coalesce(v_current.payload, '{}'::jsonb));
        else
            v_version := v_version + 1;
            v_sequence := v_sequence + 1;
            insert into icu_sync.entities as target
                (workspace_id, entity_type, entity_id, server_version, payload, deleted)
                values (v_workspace, v_type, v_entity, v_version, v_payload, v_kind = 'delete')
                on conflict (workspace_id, entity_type, entity_id) do update set
                    server_version = excluded.server_version, payload = excluded.payload,
                    deleted = excluded.deleted, updated_at = now();
            insert into icu_sync.changes
                (workspace_id, sequence, entity_type, entity_id, operation,
                 server_version, payload, user_id, device_id)
                values (v_workspace, v_sequence, v_type, v_entity, v_kind,
                        v_version, v_payload, v_user, v_device);
            v_result := jsonb_build_object(
                'operation_id', v_id, 'entity_type', v_type, 'entity_id', v_entity,
                'status', 'accepted', 'server_version', v_version,
                'change_sequence', v_sequence, 'server_payload', v_payload);
        end if;
        insert into icu_sync.receipts (workspace_id, operation_id, request_hash, response)
            values (v_workspace, v_id, v_hash, v_result);
        v_results := v_results || jsonb_build_array(v_result);
    end loop;
    update icu_sync.workspaces set change_sequence = v_sequence where id = v_workspace;
    return jsonb_build_object('results', v_results);
end;
$$;
revoke all on function public.icu_sync_push(jsonb) from public, anon, authenticated, service_role;

create or replace function public.icu_sync_pull(
    p_workspace_id uuid, p_device_id uuid, p_after bigint default 0, p_limit integer default 100
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    v_row record;
    v_result jsonb := '[]'::jsonb;
    v_item jsonb;
    v_cursor bigint := p_after;
    v_count integer := 0;
    v_bytes integer := 0;
    v_more boolean := false;
begin
    perform icu_sync.require_device(p_workspace_id, p_device_id);
    if p_after is null or p_after < 0 or p_limit is null or p_limit not between 1 and 100 then
        raise invalid_parameter_value using message = 'Invalid pull cursor or limit.';
    end if;
    if p_after > (select change_sequence from icu_sync.workspaces where id = p_workspace_id) then
        raise invalid_parameter_value using message = 'Cursor exceeds server history; rebootstrap required.';
    end if;
    for v_row in select * from icu_sync.changes
        where workspace_id = p_workspace_id and sequence > p_after
        order by sequence limit p_limit + 1 loop
        v_item := jsonb_build_object(
            'sequence', v_row.sequence, 'entity_type', v_row.entity_type,
            'entity_id', v_row.entity_id, 'operation', v_row.operation,
            'server_version', v_row.server_version, 'payload', v_row.payload);
        if v_count >= p_limit or (v_count > 0 and v_bytes + octet_length(v_item::text) > 8388608) then
            v_more := true;
            exit;
        end if;
        v_result := v_result || jsonb_build_array(v_item);
        v_count := v_count + 1;
        v_bytes := v_bytes + octet_length(v_item::text);
        v_cursor := v_row.sequence;
    end loop;
    return jsonb_build_object('changes', v_result, 'next_cursor', v_cursor, 'has_more', v_more);
end;
$$;
revoke all on function public.icu_sync_pull(uuid, uuid, bigint, integer)
    from public, anon, authenticated, service_role;
comment on schema icu_sync is 'ICU sync v1: synthetic rehearsal, client access not yet enabled';
notify pgrst, 'reload schema';
commit;
