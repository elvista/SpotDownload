import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

const HeaderContext = createContext({
  onGoHome: undefined,
  setOnGoHome: () => {},
});

export function HeaderProvider({ children }) {
  const onGoHomeRef = useRef(undefined);
  const [hasGoHome, setHasGoHome] = useState(false);

  const setOnGoHome = useCallback((fn) => {
    onGoHomeRef.current = fn;
    setHasGoHome(!!fn);
  }, []);

  const invokeGoHome = useCallback(() => {
    onGoHomeRef.current?.();
  }, []);

  const onGoHome = hasGoHome ? invokeGoHome : undefined;

  const value = useMemo(() => ({ onGoHome, setOnGoHome }), [onGoHome, setOnGoHome]);
  return <HeaderContext.Provider value={value}>{children}</HeaderContext.Provider>;
}

// Hook is colocated with provider for this small app shell.
// eslint-disable-next-line react-refresh/only-export-components -- useHeaderContext pairs with HeaderProvider
export function useHeaderContext() {
  return useContext(HeaderContext);
}
