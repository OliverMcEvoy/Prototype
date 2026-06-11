import { useCallback, useEffect, useRef, useState } from 'react'
import { LockToggleSymbol } from './LockToggleSymbol'

export function TodoPanel({ onDetachedChange }: { onDetachedChange: (detached: boolean) => void }) {
  const [floating, setFloating] = useState(false)
  const [detached, setDetached] = useState(false)
  const [position, setPosition] = useState({ top: 176, left: 0 })
  const [width, setWidth] = useState(0)
  const [dragging, setDragging] = useState(false)
  const panelRef = useRef<HTMLElement | null>(null)
  const dockBoundsRef = useRef<DOMRect | null>(null)
  const dragOffsetRef = useRef({ x: 0, y: 0 })

  const setDetachedState = useCallback(
    (nextDetached: boolean) => {
      setDetached(nextDetached)
      onDetachedChange(nextDetached)
    },
    [onDetachedChange],
  )

  const toggleFloating = useCallback(() => {
    const panel = panelRef.current

    if (!floating && panel) {
      const rect = panel.getBoundingClientRect()
      setWidth(rect.width)
      setPosition({
        top: Math.max(12, rect.top),
        left: Math.max(12, rect.left),
      })
      dockBoundsRef.current = rect
      setDetachedState(false)
      setFloating(true)
      return
    }

    setFloating(false)
    setDetachedState(false)
    setDragging(false)
  }, [floating, setDetachedState])

  const beginDrag = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (!floating) {
        return
      }

      const panel = panelRef.current
      if (!panel) {
        return
      }

      const rect = panel.getBoundingClientRect()
      dragOffsetRef.current = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }
      setDragging(true)
      event.preventDefault()
    },
    [floating],
  )

  useEffect(() => {
    if (!dragging) {
      return
    }

    const handlePointerMove = (event: PointerEvent) => {
      const panel = panelRef.current
      const dockBounds = dockBoundsRef.current
      const panelWidth = width || panel?.offsetWidth || 320
      const panelHeight = panel?.offsetHeight || 320
      const nextLeft = event.clientX - dragOffsetRef.current.x
      const nextTop = event.clientY - dragOffsetRef.current.y

      if (!detached && dockBounds) {
        const isOutsideDock =
          nextLeft < dockBounds.left - 24 ||
          nextTop < dockBounds.top - 24 ||
          nextLeft + panelWidth > dockBounds.right + 24 ||
          nextTop + panelHeight > dockBounds.bottom + 24

        if (isOutsideDock) {
          setDetachedState(true)
        }
      }

      setPosition({
        left: Math.min(Math.max(12, nextLeft), window.innerWidth - panelWidth - 12),
        top: Math.min(Math.max(12, nextTop), window.innerHeight - panelHeight - 12),
      })
    }

    const stopDragging = () => {
      setDragging(false)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', stopDragging)
    window.addEventListener('pointercancel', stopDragging)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', stopDragging)
      window.removeEventListener('pointercancel', stopDragging)
    }
  }, [detached, dragging, setDetachedState, width])

  return (
    <aside
      ref={panelRef}
      className={[
        floating ? 'card panel sidebar sidebar-floating' : 'card panel sidebar',
      ].join(' ')}
      style={
        floating
          ? {
              top: `${position.top}px`,
              left: `${position.left}px`,
              width: width ? `${width}px` : undefined,
            }
          : undefined
      }
      onPointerDown={beginDrag}
    >
      <div className="sidebar-heading">
        <h2>TODO</h2>
        <button
          className="todo-float-toggle"
          type="button"
          onClick={toggleFloating}
          onPointerDown={(event) => event.stopPropagation()}
          aria-label={floating ? 'Dock TODO panel' : 'Float TODO panel'}
          title={floating ? 'Dock TODO panel' : 'Float TODO panel'}
        >
          <LockToggleSymbol floating={floating} />
        </button>
      </div>
      <span className="todo-panel-sr-only">Project todo items</span>
      <ul className="todo-preview">
        <li>
          Implement rest of configuration options for the frontend
        </li>
        <li>
          Implement periodic refresh
        </li>
        <li>
          Matched Pairs pages and perma links
        </li>
        <li>
          Dockerise
        </li>
      </ul>
    </aside>
  )
}