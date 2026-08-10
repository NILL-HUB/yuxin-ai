from quart import request

_registered = False


def _int_arg(name, default):
    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/admin/model-providers")
    async def admin_model_provider_list():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderPageResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        req = a.SimpleNamespace(
            search=a._field(request.args.get("search") or "", ""),
            status=a._field(request.args.get("status") or "", ""),
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
        )
        result = await a._to_thread(
            a._get_service(AdminModelProviderService).list_providers,
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelProviderPageResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/model-providers/options")
    async def admin_model_provider_options():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderOptionsResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        result = await a._to_thread(
            a._get_service(AdminModelProviderService).list_provider_options
        )
        resp = AdminModelProviderOptionsResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/model-providers")
    async def admin_model_provider_create():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        payload = await request.get_json(force=True, silent=True) or {}
        errors = {}
        if not payload.get("name"):
            errors["name"] = ["name不能为空"]
        if not payload.get("label"):
            errors["label"] = ["label不能为空"]
        if not payload.get("default_base_url"):
            errors["default_base_url"] = ["default_base_url不能为空"]
        if errors:
            first_msg = next(iter(errors.values()))[0]
            return a._json_resp(
                code="validate_error", message=first_msg, data=errors, status=400
            )
        payload.setdefault("description", "")
        payload.setdefault("icon", "")
        payload.setdefault("background", "#FFFFFF")
        payload.setdefault("is_full_url", False)
        payload.setdefault("supported_model_types", ["chat"])
        payload.setdefault("status", "active")
        result = await a._to_thread(
            a._get_service(AdminModelProviderService).create_provider, payload
        )
        resp = AdminModelProviderResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/model-providers/<uuid:provider_id>")
    async def admin_model_provider_get(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        result = await a._to_thread(
            a._get_service(AdminModelProviderService).get_provider, provider_id
        )
        resp = AdminModelProviderResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/model-providers/<uuid:provider_id>")
    async def admin_model_provider_update(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        payload = await request.get_json(force=True, silent=True) or {}
        allowed_fields = [
            "label",
            "description",
            "icon",
            "background",
            "default_base_url",
            "is_full_url",
            "supported_model_types",
            "status",
        ]
        update_data = {k: v for k, v in payload.items() if k in allowed_fields}
        if not update_data:
            return a._json_resp(
                code="validate_error",
                message="No valid fields to update.",
                data={"_": ["No valid fields to update."]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminModelProviderService).update_provider,
            provider_id,
            update_data,
        )
        resp = AdminModelProviderResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/model-providers/<uuid:provider_id>")
    async def admin_model_provider_delete(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.admin_model_provider_service import AdminModelProviderService

        await a._to_thread(
            a._get_service(AdminModelProviderService).delete_provider, provider_id
        )
        return a._ok_msg("删除成功")

    @quart_app.post("/admin/model-providers/<uuid:provider_id>/status")
    async def admin_model_provider_status(provider_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_provider_schema import AdminModelProviderResp
        from internal.service.admin_model_provider_service import AdminModelProviderService

        payload = await request.get_json(force=True, silent=True) or {}
        status = payload.get("status")
        if not status:
            return a._json_resp(
                code="validate_error",
                message="status不能为空",
                data={"status": ["status不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminModelProviderService).set_provider_status,
            provider_id,
            status,
        )
        resp = AdminModelProviderResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/models")
    async def admin_model_pool_list():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelPageResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        req = a.SimpleNamespace(
            search=a._field(request.args.get("search") or "", ""),
            provider=a._field(request.args.get("provider") or "", ""),
            tier=a._field(request.args.get("tier") or "", ""),
            status=a._field(request.args.get("status") or "", ""),
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
        )
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).list_models,
            search=req.search.data,
            provider=req.provider.data,
            tier=req.tier.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/models")
    async def admin_model_pool_create():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).create_model, payload
        )
        resp = AdminModelResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/models/<uuid:model_id>")
    async def admin_model_pool_get(model_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        result = await a._to_thread(
            a._get_service(AdminModelPoolService).get_model, model_id
        )
        resp = AdminModelResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/models/<uuid:model_id>")
    async def admin_model_pool_update(model_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).update_model, model_id, payload
        )
        resp = AdminModelResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/models/<uuid:model_id>")
    async def admin_model_pool_delete(model_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.admin_model_pool_service import AdminModelPoolService

        await a._to_thread(
            a._get_service(AdminModelPoolService).delete_model, model_id
        )
        return a._ok_msg("删除模型配置成功")

    @quart_app.post("/admin/models/<uuid:model_id>/status")
    async def admin_model_pool_status(model_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        status = payload.get("status")
        if not status:
            return a._json_resp(
                code="validate_error",
                message="status不能为空",
                data={"status": ["status不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).set_model_status, model_id, status
        )
        resp = AdminModelResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/model-keys")
    async def admin_model_key_list():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelKeyPageResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        req = a.SimpleNamespace(
            provider=a._field(request.args.get("provider") or "", ""),
            status=a._field(request.args.get("status") or "", ""),
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
        )
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).list_keys,
            provider=req.provider.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelKeyPageResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/model-keys")
    async def admin_model_key_create():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelKeyResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).create_key, payload
        )
        resp = AdminModelKeyResp()
        return a._ok(resp.dump(result))

    @quart_app.patch("/admin/model-keys/<uuid:key_id>")
    async def admin_model_key_update(key_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelKeyResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).update_key, key_id, payload
        )
        resp = AdminModelKeyResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/model-keys/<uuid:key_id>")
    async def admin_model_key_delete(key_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.admin_model_pool_service import AdminModelPoolService

        await a._to_thread(
            a._get_service(AdminModelPoolService).delete_key, key_id
        )
        return a._ok_msg("删除模型Key成功")

    @quart_app.post("/admin/model-keys/<uuid:key_id>/status")
    async def admin_model_key_status(key_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelKeyResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        status = payload.get("status")
        if not status:
            return a._json_resp(
                code="validate_error",
                message="status不能为空",
                data={"status": ["status不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).set_key_status, key_id, status
        )
        resp = AdminModelKeyResp()
        return a._ok(resp.dump(result))

    @quart_app.get("/admin/model-tiers")
    async def admin_model_tier_list():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelTierListResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        result = await a._to_thread(
            a._get_service(AdminModelPoolService).list_tier_policies
        )
        resp = AdminModelTierListResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/model-tiers")
    async def admin_model_tier_create():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelTierResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).create_tier_policy, payload
        )
        resp = AdminModelTierResp()
        return a._ok(resp.dump(result))

    @quart_app.put("/admin/model-tiers/<string:tier_code>")
    async def admin_model_tier_update(tier_code):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminModelTierResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).update_tier_policy,
            tier_code,
            payload,
        )
        resp = AdminModelTierResp()
        return a._ok(resp.dump(result))

    @quart_app.delete("/admin/model-tiers/<string:tier_code>")
    async def admin_model_tier_delete(tier_code):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.service.admin_model_pool_service import AdminModelPoolService

        await a._to_thread(
            a._get_service(AdminModelPoolService).delete_tier_policy, tier_code
        )
        return a._ok_msg("删除档位策略成功")

    @quart_app.get("/admin/cost-policies")
    async def admin_cost_policy_list():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminCostPolicyListResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        result = await a._to_thread(
            a._get_service(AdminModelPoolService).list_cost_policies
        )
        resp = AdminCostPolicyListResp()
        return a._ok(resp.dump(result))

    @quart_app.post("/admin/cost-policies")
    async def admin_cost_policy_create():
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminCostPolicyResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).create_cost_policy, payload
        )
        resp = AdminCostPolicyResp()
        return a._ok(resp.dump(result))

    @quart_app.put("/admin/cost-policies/<uuid:policy_id>")
    async def admin_cost_policy_update(policy_id):
        from app.http import asgi_app as a
        account, err = await a._resolve_account()
        if err is not None:
            return err
        from internal.schema.admin_model_pool_schema import AdminCostPolicyResp
        from internal.service.admin_model_pool_service import AdminModelPoolService

        payload = await request.get_json(force=True, silent=True) or {}
        result = await a._to_thread(
            a._get_service(AdminModelPoolService).update_cost_policy,
            policy_id,
            payload,
        )
        resp = AdminCostPolicyResp()
        return a._ok(resp.dump(result))
