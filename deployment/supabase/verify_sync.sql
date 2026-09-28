-- Synthetic functional verification. All test records are rolled back.
begin;
do $$
declare
    w uuid := gen_random_uuid();
    u uuid := gen_random_uuid();
    a uuid := gen_random_uuid();
    b uuid := gen_random_uuid();
    c uuid := gen_random_uuid();
    e uuid := gen_random_uuid();
    op uuid := gen_random_uuid();
    req jsonb;
    first_result jsonb;
    result jsonb;
    denied boolean;
begin
    insert into icu_sync.workspaces(id) values (w);
    insert into icu_sync.members values (w, u);
    insert into icu_sync.devices(workspace_id, user_id, device_id, label)
        values (w,u,a,'Synthetic laptop'),(w,u,b,'Synthetic work'),(w,u,c,'Synthetic desktop');
    perform set_config('request.jwt.claim.sub', u::text, true);
    req := jsonb_build_object('workspace_id',w,'device_id',a,'operations',jsonb_build_array(
        jsonb_build_object('operation_id',op,'entity_type','synthetic_patient','entity_id',e,
            'operation','upsert','base_server_version',0,'payload',jsonb_build_object('note','Synthetic A'))));
    first_result := public.icu_sync_push(req);
    assert first_result#>>'{results,0,status}' = 'accepted', 'First push failed';
    assert public.icu_sync_push(req) = first_result, 'Retry is not idempotent';
    assert (public.icu_sync_pull(w,b,0,100)->>'next_cursor')::int = 1, 'Work pull failed';
    assert (public.icu_sync_pull(w,c,0,100)->>'next_cursor')::int = 1, 'Desktop pull failed';

    -- Same operation ID must never accept new content.
    denied := false;
    begin
        perform public.icu_sync_push(jsonb_set(req,'{operations,0,payload,note}','"changed"'));
    exception when invalid_parameter_value then denied := true;
    end;
    assert denied, 'Reused operation identity accepted';

    req := jsonb_set(req,'{device_id}',to_jsonb(b));
    req := jsonb_set(req,'{operations,0,operation_id}',to_jsonb(gen_random_uuid()));
    result := public.icu_sync_push(req);
    assert result#>>'{results,0,status}' = 'conflict', 'Stale edit was accepted';
    assert result#>>'{results,0,server_payload,note}' = 'Synthetic A', 'Conflict lost server text';

    -- A bad second operation rolls back the entire batch.
    denied := false;
    begin
        req := jsonb_set(req,'{operations,0,operation_id}',to_jsonb(gen_random_uuid()));
        req := jsonb_set(req,'{operations,0,base_server_version}','1');
        req := jsonb_set(req,'{operations}',(req->'operations') || jsonb_build_array('{}'::jsonb));
        perform public.icu_sync_push(req);
    exception when invalid_parameter_value then denied := true;
    end;
    assert denied, 'Malformed batch accepted';
    assert (select change_sequence from icu_sync.workspaces where id=w)=1, 'Partial batch committed';

    req := jsonb_set(req,'{operations}',jsonb_build_array(req#>'{operations,0}'));
    req := jsonb_set(req,'{operations,0,operation}','"delete"');
    req := jsonb_set(req,'{operations,0,payload}','{}');
    result := public.icu_sync_push(req);
    assert result#>>'{results,0,status}' = 'accepted', 'Delete failed';
    assert (public.icu_sync_pull(w,c,0,1)->>'has_more')::boolean, 'Pagination failed';
    assert public.icu_sync_pull(w,c,1,1)#>>'{changes,0,operation}'='delete', 'Tombstone missing';
    assert not (public.icu_sync_pull(w,c,2,1)->>'has_more')::boolean, 'Empty pull failed';

    denied := false;
    begin
        perform public.icu_sync_pull(gen_random_uuid(),c,0,1);
    exception when insufficient_privilege then denied := true;
    end;
    assert denied, 'Cross-workspace access allowed';
    update icu_sync.devices set revoked_at=now() where workspace_id=w and device_id=c;
    denied := false;
    begin
        perform public.icu_sync_pull(w,c,0,1);
    exception when insufficient_privilege then denied := true;
    end;
    assert denied, 'Revoked device allowed';
    perform set_config('request.jwt.claim.sub', gen_random_uuid()::text, true);
    denied := false;
    begin
        perform public.icu_sync_pull(w,a,0,1);
    exception when insufficient_privilege then denied := true;
    end;
    assert denied, 'Different user allowed';
    perform set_config('request.jwt.claim.sub', '', true);
    denied := false;
    begin
        perform public.icu_sync_pull(w,a,0,1);
    exception when insufficient_privilege then denied := true;
    end;
    assert denied, 'Unauthenticated caller allowed';
    assert not has_function_privilege('anon','public.icu_sync_push(jsonb)','EXECUTE'), 'Anonymous grant';
    assert not has_table_privilege('authenticated','icu_sync.entities','SELECT'), 'Direct table access';
end;
$$;
select 'PASS: three synthetic devices, replay, conflicts, atomicity, tombstones, pagination, authorization' as verification;
rollback;
