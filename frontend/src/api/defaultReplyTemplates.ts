import { del, get, post, put } from '@/utils/request'
import type { ApiResponse } from '@/types'
import type { ItemDefaultReplyConfig } from '@/api/items'

const PREFIX = '/api/v1/default-reply-templates'

export interface DefaultReplyTemplate extends Omit<ItemDefaultReplyConfig, 'item_id'> {
  id: number
  owner_id?: number
  name: string
  bound_count?: number
  created_at?: string
  updated_at?: string
}

export interface DefaultReplyTemplateListResult {
  list: DefaultReplyTemplate[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface DefaultReplyTemplateItem {
  account_id: string
  item_id: string
  title?: string
  price?: string
}

export interface ItemDefaultReplyTemplateBinding {
  account_id: string
  item_id: string
  template: DefaultReplyTemplate | null
}

export type DefaultReplyTemplatePayload = Omit<
  DefaultReplyTemplate,
  'id' | 'owner_id' | 'bound_count' | 'created_at' | 'updated_at'
>

export const listDefaultReplyTemplates = (
  page = 1,
  pageSize = 50,
  search = '',
): Promise<DefaultReplyTemplateListResult> => {
  const params = new URLSearchParams()
  params.append('page', String(page))
  params.append('page_size', String(pageSize))
  if (search.trim()) params.append('search', search.trim())
  return get(`${PREFIX}?${params.toString()}`)
}

export const getDefaultReplyTemplate = (templateId: number): Promise<DefaultReplyTemplate> => {
  return get(`${PREFIX}/${templateId}`)
}

export const createDefaultReplyTemplate = (
  data: DefaultReplyTemplatePayload,
): Promise<ApiResponse<{ id: number }>> => {
  return post(PREFIX, data)
}

export const updateDefaultReplyTemplate = (
  templateId: number,
  data: DefaultReplyTemplatePayload,
): Promise<ApiResponse> => {
  return put(`${PREFIX}/${templateId}`, data)
}

export const deleteDefaultReplyTemplate = (templateId: number): Promise<ApiResponse> => {
  return del(`${PREFIX}/${templateId}`)
}

export const uploadDefaultReplyTemplateImage = async (
  image: File,
): Promise<{ success: boolean; image_url?: string; message?: string }> => {
  const formData = new FormData()
  formData.append('image', image)
  return post(`${PREFIX}/upload-image`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const getDefaultReplyTemplateItems = (
  templateId: number,
): Promise<{ list: DefaultReplyTemplateItem[]; total: number }> => {
  return get(`${PREFIX}/${templateId}/items`)
}

export const updateDefaultReplyTemplateItems = (
  templateId: number,
  accountId: string,
  itemIds: string[],
): Promise<ApiResponse<{ added: number; removed: number }>> => {
  return put(`${PREFIX}/${templateId}/items`, { account_id: accountId, item_ids: itemIds })
}

export const getItemDefaultReplyTemplate = (
  accountId: string,
  itemId: string,
): Promise<ApiResponse<ItemDefaultReplyTemplateBinding>> => {
  const params = new URLSearchParams()
  params.append('account_id', accountId)
  params.append('item_id', itemId)
  return get(`${PREFIX}/item-binding?${params.toString()}`)
}

export const bindItemDefaultReplyTemplate = (
  accountId: string,
  itemId: string,
  templateId: number | null,
): Promise<ApiResponse> => {
  return put(`${PREFIX}/item-binding`, {
    account_id: accountId,
    item_id: itemId,
    template_id: templateId,
  })
}
