import { login } from './login.js';
import { logout } from './logout.js';
import { validate } from './validate.js';
import { submit } from './submit.js';

// Route name = the path after /api/vN/. One handler serves every board and license type —
// the board/licenseType come in the payload, so login and submit are the same request
// whether the applicant is an Electrician apprentice or a Barber.
//
// If some license type ever genuinely needs its own handler, it opts in with a longer key
// ('apprentice/login' → /api/apprentice/login) and the step overrides its form action to
// match. Nothing needs that yet, so nothing declares it.
export const routes = {
	login,
	logout,
	validate,
	submit,
};
