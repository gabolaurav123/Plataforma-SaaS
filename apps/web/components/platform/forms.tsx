'use client';
import { useId, useState, type ReactNode } from 'react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';

export type Field = {
  key: string;
  label: string;
  type?:
    | 'text'
    | 'textarea'
    | 'number'
    | 'select'
    | 'switch'
    | 'password'
    | 'date';
  options?: { value: string; label: string }[];
  initial?: string | number | boolean;
  required?: boolean;
  hint?: string;
};
export function Form({
  fields,
  submit,
  label = 'Guardar',
  children,
}: {
  fields: Field[];
  submit: (data: Record<string, string | number | boolean>) => Promise<void>;
  label?: string;
  children?: ReactNode;
}) {
  const formId = useId();
  const [values, setValues] = useState<
    Record<string, string | number | boolean>
  >(() =>
    Object.fromEntries(
      fields.map((f) => [
        f.key,
        f.initial ?? (f.type === 'switch' ? false : ''),
      ]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  return (
    <form
      className="engine-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError('');
        setSuccess(false);
        try {
          await submit(values);
          setSuccess(true);
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      {fields.map((field) => (
        <label
          className={'field ' + (field.type === 'switch' ? 'switch-field' : '')}
          key={field.key}
          htmlFor={formId + field.key}
        >
          <span>{field.label}</span>
          {field.type === 'textarea' ? (
            <Textarea
              id={formId + field.key}
              value={String(values[field.key] ?? '')}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.key]: e.target.value }))
              }
              required={field.required}
              rows={4}
            />
          ) : field.type === 'select' ? (
            <Select
              value={String(values[field.key] ?? '')}
              onValueChange={(value) =>
                setValues((v) => ({ ...v, [field.key]: String(value) }))
              }
            >
              <SelectTrigger id={formId + field.key}>
                <SelectValue placeholder="Seleccionar" />
              </SelectTrigger>
              <SelectContent>
                {field.options?.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : field.type === 'switch' ? (
            <Switch
              id={formId + field.key}
              checked={Boolean(values[field.key])}
              onCheckedChange={(checked) =>
                setValues((v) => ({ ...v, [field.key]: checked }))
              }
            />
          ) : (
            <Input
              id={formId + field.key}
              type={field.type || 'text'}
              value={String(values[field.key] ?? '')}
              onChange={(e) =>
                setValues((v) => ({
                  ...v,
                  [field.key]:
                    field.type === 'number'
                      ? Number(e.target.value)
                      : e.target.value,
                }))
              }
              required={field.required}
              autoComplete="off"
            />
          )}
          {field.hint && <small>{field.hint}</small>}
        </label>
      ))}
      {children}
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {success && (
        <output className="success-box">Guardado correctamente.</output>
      )}
      <Button type="submit" disabled={busy}>
        {busy ? 'Guardando…' : label}
      </Button>
    </form>
  );
}
