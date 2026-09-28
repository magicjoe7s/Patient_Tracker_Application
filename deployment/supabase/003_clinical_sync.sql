-- Enable versioned patient snapshots for the already-authorized owner and devices.
-- Existing account/device checks, private tables, and RPC grants are preserved.
begin;
alter table icu_sync.entities drop constraint entities_entity_type_check;
alter table icu_sync.entities add constraint entities_entity_type_check
    check (entity_type in ('synthetic_patient', 'patient_snapshot_v1'));
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
           or v_type is null or v_type not in ('synthetic_patient', 'patient_snapshot_v1')
           or v_kind is null or v_kind not in ('upsert', 'delete')
           or jsonb_typeof(v_payload) is distinct from 'object'
           or jsonb_typeof(v_op->'base_server_version') is distinct from 'number'
           or (v_op->>'base_server_version') !~ '^[0-9]{1,15}$' then
            raise invalid_parameter_value using message = 'Invalid sync operation.';
        end if;
        if v_type = 'patient_snapshot_v1' and (
            v_payload->'schema_version' is distinct from '1'::jsonb
            or (v_kind = 'delete' and v_payload->'patient' is distinct from 'null'::jsonb)
            or (v_kind = 'upsert' and (
                v_payload#>>'{patient,type}' is distinct from 'Patient'
                or v_payload#>>'{patient,fields,id,type}' is distinct from 'UUID'
                or v_payload#>>'{patient,fields,id,value}' is distinct from v_entity::text
            ))
        ) then
            raise invalid_parameter_value using message = 'Invalid patient snapshot.';
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
comment on schema icu_sync is 'ICU sync v1: authorized patient snapshots';
notify pgrst, 'reload schema';
commit;
