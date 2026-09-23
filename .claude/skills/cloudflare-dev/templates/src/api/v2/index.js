import { routes as v1 } from '../v1/index.js';
import { login } from './login.js';

// v2 = v1 plus overrides. Only changed handlers live in this folder.
export const routes = { ...v1, login };
