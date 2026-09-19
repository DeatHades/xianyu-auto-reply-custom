import { useEffect, useRef, useState } from 'react'
import { Edit2, ImagePlus, Loader2, MessageSquare, Package, Plus, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { getAccountDetails } from '@/api/accounts'
import { getItemsPaginated } from '@/api/items'
import {
  createDefaultReplyTemplate,
  deleteDefaultReplyTemplate,
  getDefaultReplyTemplate,
  getDefaultReplyTemplateItems,
  listDefaultReplyTemplates,
  updateDefaultReplyTemplate,
  updateDefaultReplyTemplateItems,
  uploadDefaultReplyTemplateImage,
  type DefaultReplyTemplate,
  type DefaultReplyTemplatePayload,
} from '@/api/defaultReplyTemplates'
import { getUserSetting } from '@/api/settings'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { PageLoading } from '@/components/common/Loading'
import { useUIStore } from '@/store/uiStore'
import type { Account, Item } from '@/types'
import LocationContactReplyFields, { DEFAULT_LOCATION_TITLE, type LocationContactReplyValue } from '@/pages/common/LocationContactReplyFields'

const EMPTY_LOCATION: LocationContactReplyValue = {
  location_name: '',
  location_longitude: '',
  location_latitude: '',
  location_title: DEFAULT_LOCATION_TITLE,
  location_subtitle: '',
}

const emptyForm = (): DefaultReplyTemplatePayload => ({
  name: '',
  enabled: true,
  reply_type: 'text',
  reply_content: '',
  reply_image: '',
  api_url: '',
  api_timeout: 80,
  reply_once: false,
  ...EMPTY_LOCATION,
})

export function DefaultReplyTemplates() {
  const { addToast } = useUIStore()
  const imageInputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(true)
  const [templates, setTemplates] = useState<DefaultReplyTemplate[]>([])
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<DefaultReplyTemplate | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [form, setForm] = useState<DefaultReplyTemplatePayload>(emptyForm())
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DefaultReplyTemplate | null>(null)

  const [bindingTemplate, setBindingTemplate] = useState<DefaultReplyTemplate | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [bindAccountId, setBindAccountId] = useState('')
  const [bindKeyword, setBindKeyword] = useState('')
  const [bindItems, setBindItems] = useState<Item[]>([])
  const [selectedItemIds, setSelectedItemIds] = useState<Set<string>>(new Set())
  const [bindingLoading, setBindingLoading] = useState(false)
  const [bindingSaving, setBindingSaving] = useState(false)

  const loadTemplates = async (keyword = search) => {
    setLoading(true)
    try {
      const result = await listDefaultReplyTemplates(1, 100, keyword)
      setTemplates(result.list || [])
    } catch {
      addToast({ type: 'error', message: '加载默认回复模板失败' })
    } finally {
      setLoading(false)
    }
  }

  const loadAccounts = async (): Promise<Account[]> => {
    try {
      const list = await getAccountDetails()
      setAccounts(list)
      return list
    } catch {
      addToast({ type: 'error', message: '加载账号列表失败' })
      return []
    }
  }

  useEffect(() => {
    loadTemplates('')
    loadAccounts()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(emptyForm())
    setShowEditor(true)
  }

  const openEdit = async (template: DefaultReplyTemplate) => {
    setShowEditor(true)
    setEditing(template)
    try {
      const detail = await getDefaultReplyTemplate(template.id)
      setForm({
        name: detail.name || '',
        enabled: detail.enabled ?? true,
        reply_type: detail.reply_type || 'text',
        reply_content: detail.reply_content || '',
        reply_image: detail.reply_image || '',
        api_url: detail.api_url || '',
        api_timeout: detail.api_timeout || 80,
        reply_once: detail.reply_once || false,
        location_name: detail.location_name || '',
        location_longitude: detail.location_longitude || '',
        location_latitude: detail.location_latitude || '',
        location_title: detail.location_title || DEFAULT_LOCATION_TITLE,
        location_subtitle: detail.location_subtitle || '',
      })
    } catch {
      addToast({ type: 'error', message: '加载模板详情失败' })
      setShowEditor(false)
    }
  }

  const validateForm = async () => {
    if (!form.name.trim()) {
      addToast({ type: 'warning', message: '请输入模板名称' })
      return false
    }
    if (form.reply_type === 'api' && !form.api_url?.trim()) {
      addToast({ type: 'warning', message: '请输入 API 地址' })
      return false
    }
    if (form.reply_type === 'external_contact') {
      const [remoteUrl, remoteSecret] = await Promise.all([
        getUserSetting('location_chat.remote_url'),
        getUserSetting('location_chat.remote_secret_key'),
      ])
      if (!remoteUrl.success || !remoteUrl.value?.trim() || !remoteSecret.success || !remoteSecret.value?.trim()) {
        addToast({ type: 'warning', message: '请先到个人设置里填写位置聊天远程URL和秘钥' })
        return false
      }
      if (!form.location_name || !form.location_longitude || !form.location_latitude) {
        addToast({ type: 'warning', message: '请选择带经纬度的定位信息' })
        return false
      }
    }
    return true
  }

  const saveTemplate = async () => {
    if (!(await validateForm())) return
    setSaving(true)
    try {
      const payload = {
        ...form,
        name: form.name.trim(),
        api_timeout: Number(form.api_timeout) || 80,
        location_title: form.location_title?.trim() || DEFAULT_LOCATION_TITLE,
      }
      const result = editing
        ? await updateDefaultReplyTemplate(editing.id, payload)
        : await createDefaultReplyTemplate(payload)
      if (result.success) {
        addToast({ type: 'success', message: editing ? '模板已更新' : '模板已创建' })
        setShowEditor(false)
        await loadTemplates()
      } else {
        addToast({ type: 'error', message: result.message || '保存失败' })
      }
    } catch {
      addToast({ type: 'error', message: '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  const uploadImage = async (file?: File) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      addToast({ type: 'error', message: '只支持上传图片文件' })
      return
    }
    setUploading(true)
    try {
      const result = await uploadDefaultReplyTemplateImage(file)
      if (result.success && result.image_url) {
        setForm((current) => ({ ...current, reply_image: result.image_url || '' }))
        addToast({ type: 'success', message: '图片上传成功' })
      } else {
        addToast({ type: 'error', message: result.message || '图片上传失败' })
      }
    } finally {
      setUploading(false)
      if (imageInputRef.current) imageInputRef.current.value = ''
    }
  }

  const openBinding = async (template: DefaultReplyTemplate) => {
    setBindingTemplate(template)
    setBindItems([])
    setSelectedItemIds(new Set())
    const availableAccounts = accounts.length > 0 ? accounts : await loadAccounts()
    const defaultAccount = bindAccountId || availableAccounts[0]?.id || ''
    setBindAccountId(defaultAccount)
    setBindKeyword('')
    if (!defaultAccount) {
      addToast({ type: 'warning', message: '请先添加闲鱼账号并同步商品' })
      return
    }
    await loadBindingItems(template, defaultAccount, '')
  }

  const loadBindingItems = async (template = bindingTemplate, accountId = bindAccountId, keyword = bindKeyword) => {
    if (!template || !accountId) {
      setBindItems([])
      setSelectedItemIds(new Set())
      return
    }
    setBindingLoading(true)
    try {
      const [itemsResult, boundResult] = await Promise.all([
        getItemsPaginated(1, 100, accountId, { keyword: keyword.trim() || null }),
        getDefaultReplyTemplateItems(template.id),
      ])
      setBindItems(itemsResult.data || [])
      setSelectedItemIds(new Set(
        (boundResult.list || [])
          .filter((item) => item.account_id === accountId)
          .map((item) => item.item_id),
      ))
    } catch {
      addToast({ type: 'error', message: '加载可绑定商品失败' })
    } finally {
      setBindingLoading(false)
    }
  }

  const saveBinding = async () => {
    if (!bindingTemplate || !bindAccountId) return
    setBindingSaving(true)
    try {
      const result = await updateDefaultReplyTemplateItems(bindingTemplate.id, bindAccountId, Array.from(selectedItemIds))
      if (result.success) {
        addToast({ type: 'success', message: result.message || '模板绑定已更新' })
        setBindingTemplate(null)
        await loadTemplates()
      } else {
        addToast({ type: 'error', message: result.message || '保存绑定失败' })
      }
    } catch {
      addToast({ type: 'error', message: '保存绑定失败' })
    } finally {
      setBindingSaving(false)
    }
  }

  const removeTemplate = async () => {
    if (!deleteTarget) return
    const result = await deleteDefaultReplyTemplate(deleteTarget.id)
    if (result.success) {
      addToast({ type: 'success', message: '模板已删除' })
      setDeleteTarget(null)
      loadTemplates()
    } else {
      addToast({ type: 'error', message: result.message || '删除失败' })
    }
  }

  if (loading) return <PageLoading />

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">默认回复模板</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            先建模板，再批量绑定商品；商品直接填写的默认回复仍然优先。
          </p>
        </div>
        <button className="btn-ios-primary flex items-center gap-2" onClick={openCreate}>
          <Plus className="w-4 h-4" />
          新增模板
        </button>
      </div>

      <div className="card-ios p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && loadTemplates(search)}
              className="input-ios pl-9"
              placeholder="搜索模板名称"
            />
          </div>
          <button className="btn-ios-secondary flex items-center gap-2" onClick={() => loadTemplates(search)}>
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {templates.map((template) => (
          <div key={template.id} className="card-ios p-5 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-semibold text-slate-900 dark:text-slate-100 truncate">{template.name}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {template.enabled ? '已启用' : '已关闭'} · {template.reply_type === 'api' ? 'API接口' : template.reply_type === 'external_contact' ? '站外联系方式' : '默认回复'} · 已绑定 {template.bound_count || 0} 个商品
                </div>
              </div>
              <span className={`px-2 py-1 rounded-full text-xs ${template.enabled ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}`}>
                {template.enabled ? '启用' : '关闭'}
              </span>
            </div>
            {template.reply_content && (
              <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-3 whitespace-pre-wrap">{template.reply_content}</p>
            )}
            <div className="flex flex-wrap gap-2">
              <button className="btn-ios-secondary text-sm flex items-center gap-1" onClick={() => openBinding(template)}>
                <Package className="w-4 h-4" />
                绑定商品
              </button>
              <button className="btn-ios-secondary text-sm flex items-center gap-1" onClick={() => openEdit(template)}>
                <Edit2 className="w-4 h-4" />
                编辑
              </button>
              <button className="btn-ios-danger text-sm flex items-center gap-1" onClick={() => setDeleteTarget(template)}>
                <Trash2 className="w-4 h-4" />
                删除
              </button>
            </div>
          </div>
        ))}
        {templates.length === 0 && (
          <div className="card-ios p-10 text-center text-slate-500 dark:text-slate-400 md:col-span-2 xl:col-span-3">
            暂无默认回复模板
          </div>
        )}
      </div>

      {showEditor && (
        <div className="modal-overlay" style={{ zIndex: 60 }}>
          <div className="modal-content max-w-2xl">
            <div className="modal-header">
              <h2 className="modal-title flex items-center gap-2">
                <MessageSquare className="w-5 h-5 text-purple-500" />
                {editing ? '编辑默认回复模板' : '新增默认回复模板'}
              </h2>
              <button className="modal-close" onClick={() => setShowEditor(false)}>
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="modal-body space-y-4">
              <div className="input-group">
                <label className="input-label">模板名称</label>
                <input className="input-ios" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：虚拟资料通用回复" />
              </div>
              <label className="flex items-center gap-3">
                <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="w-4 h-4" />
                <span className="text-sm text-slate-700 dark:text-slate-300">启用模板</span>
              </label>
              <div className="input-group">
                <label className="input-label">回复类型</label>
                <div className="flex gap-2">
                  {([
                    { value: 'text', label: '默认回复' },
                    { value: 'api', label: 'API接口' },
                    { value: 'external_contact', label: '站外联系方式' },
                  ] as const).map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setForm({ ...form, reply_type: option.value })}
                      className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border ${
                        form.reply_type === option.value
                          ? 'bg-purple-600 text-white border-purple-600'
                          : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-600'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {form.reply_type === 'api' && (
                <>
                  <div className="input-group">
                    <label className="input-label">API 地址</label>
                    <input className="input-ios" value={form.api_url || ''} onChange={(e) => setForm({ ...form, api_url: e.target.value })} placeholder="https://example.com/api/reply" />
                  </div>
                  <div className="input-group">
                    <label className="input-label">超时时间（秒）</label>
                    <input type="number" min={1} max={120} className="input-ios" value={form.api_timeout || 80} onChange={(e) => setForm({ ...form, api_timeout: Number(e.target.value) || 80 })} />
                  </div>
                </>
              )}

              {form.reply_type === 'external_contact' && (
                <LocationContactReplyFields
                  value={{
                    location_name: form.location_name || '',
                    location_longitude: form.location_longitude || '',
                    location_latitude: form.location_latitude || '',
                    location_title: form.location_title || DEFAULT_LOCATION_TITLE,
                    location_subtitle: form.location_subtitle || '',
                  }}
                  onChange={(next) => setForm({ ...form, ...next })}
                />
              )}

              {form.reply_type === 'text' && (
                <>
                  <div className="input-group">
                    <label className="input-label">回复内容</label>
                    <textarea
                      className="input-ios h-32 resize-none"
                      value={form.reply_content || ''}
                      onChange={(e) => setForm({ ...form, reply_content: e.target.value })}
                      placeholder="输入模板回复内容，可用 ###### 分隔多条消息"
                    />
                  </div>
                  <div className="input-group">
                    <label className="input-label">回复图片（可选）</label>
                    <input ref={imageInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => uploadImage(e.target.files?.[0])} />
                    {form.reply_image ? (
                      <div className="relative inline-block">
                        <img src={form.reply_image} alt="回复图片" className="max-w-[200px] max-h-[150px] rounded-lg border border-slate-200 dark:border-slate-700" />
                        <button type="button" onClick={() => setForm({ ...form, reply_image: '' })} className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 text-white rounded-full flex items-center justify-center">
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    ) : (
                      <button type="button" onClick={() => imageInputRef.current?.click()} disabled={uploading} className="flex items-center gap-2 px-4 py-2 border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-lg">
                        {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImagePlus className="w-4 h-4 text-slate-400" />}
                        <span className="text-sm text-slate-500">{uploading ? '上传中...' : '点击上传图片'}</span>
                      </button>
                    )}
                  </div>
                </>
              )}

              <label className="flex items-center gap-3">
                <input type="checkbox" checked={!!form.reply_once} onChange={(e) => setForm({ ...form, reply_once: e.target.checked })} className="w-4 h-4" />
                <span className="text-sm text-slate-700 dark:text-slate-300">只回复一次（同一用户咨询同一商品只回复一次）</span>
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn-ios-secondary" onClick={() => setShowEditor(false)} disabled={saving}>取消</button>
              <button className="btn-ios-primary" onClick={saveTemplate} disabled={saving}>
                {saving ? <span className="flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />保存中...</span> : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {bindingTemplate && (
        <div className="modal-overlay" style={{ zIndex: 60 }}>
          <div className="modal-content max-w-4xl">
            <div className="modal-header">
              <h2 className="modal-title">绑定商品：{bindingTemplate.name}</h2>
              <button className="modal-close" onClick={() => setBindingTemplate(null)}>
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="modal-body space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-[220px_1fr_auto] gap-3">
                <select
                  className="input-ios"
                  value={bindAccountId}
                  onChange={(e) => {
                    setBindAccountId(e.target.value)
                    loadBindingItems(bindingTemplate, e.target.value, bindKeyword)
                  }}
                >
                  <option value="">选择账号</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>{account.note || account.id}</option>
                  ))}
                </select>
                <input
                  className="input-ios"
                  value={bindKeyword}
                  onChange={(e) => setBindKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && loadBindingItems()}
                  placeholder="搜索商品标题或ID"
                />
                <button className="btn-ios-secondary" onClick={() => loadBindingItems()}>查询</button>
              </div>
              <div className="text-xs text-amber-600 dark:text-amber-400">
                一个商品最多绑定一个默认回复模板；保存后会替换该账号下当前模板的绑定商品。
              </div>
              {bindingLoading ? (
                <div className="py-10 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-purple-500" /></div>
              ) : (
                <div className="max-h-[55vh] overflow-y-auto border border-slate-200 dark:border-slate-700 rounded-xl divide-y divide-slate-100 dark:divide-slate-800">
                  {bindItems.map((item) => (
                    <label key={item.item_id} className="flex items-start gap-3 p-3 hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selectedItemIds.has(item.item_id)}
                        onChange={(e) => {
                          const next = new Set(selectedItemIds)
                          if (e.target.checked) next.add(item.item_id)
                          else next.delete(item.item_id)
                          setSelectedItemIds(next)
                        }}
                        className="mt-1 w-4 h-4"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-slate-800 dark:text-slate-100 line-clamp-2">{item.item_title || item.title || item.item_id}</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">商品ID：{item.item_id}</div>
                      </div>
                      {(item.item_price || item.price) && <div className="text-sm text-amber-600 dark:text-amber-400">{item.item_price || `¥${item.price}`}</div>}
                    </label>
                  ))}
                  {bindItems.length === 0 && <div className="p-8 text-center text-slate-500 dark:text-slate-400">暂无可绑定商品</div>}
                </div>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-ios-secondary" onClick={() => setBindingTemplate(null)} disabled={bindingSaving}>取消</button>
              <button className="btn-ios-primary" onClick={saveBinding} disabled={bindingSaving || !bindAccountId}>
                {bindingSaving ? <span className="flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />保存中...</span> : `保存绑定（${selectedItemIds.size} 个）`}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <ConfirmModal
          isOpen={!!deleteTarget}
          title="删除默认回复模板"
          message={`确定删除「${deleteTarget.name}」吗？删除后会同时清除它与商品的绑定关系。`}
          confirmText="删除"
          cancelText="取消"
          type="danger"
          onConfirm={removeTemplate}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}

export default DefaultReplyTemplates
