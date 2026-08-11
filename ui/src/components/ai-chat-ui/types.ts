export type AiToolRow = {
  old?: number | string | null
  cur?: number | string | null
  type?: 'ctx' | 'add' | 'del'
  text?: string
  title?: string
  url?: string
  status?: 'pending' | 'loading' | 'done' | 'error'
}
