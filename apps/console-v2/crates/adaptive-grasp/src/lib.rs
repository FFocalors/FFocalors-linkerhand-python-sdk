//! Hardware-independent adaptive grasp state machine and profile limits.
use serde::{Deserialize, Serialize};
use thiserror::Error;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Profile {
    O6,
    L6,
    L7,
    L10,
    L20,
}
impl Profile {
    pub fn joint_count(&self) -> usize {
        match self {
            Self::O6 => 6,
            Self::L6 => 6,
            Self::L7 => 7,
            Self::L10 => 10,
            Self::L20 => 20,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GraspState {
    Idle,
    Calibrating,
    Ready,
    Grasping,
    Holding,
    Releasing,
    Aborted,
}
#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum GraspError {
    #[error("profile has {expected} joints but got {actual}")]
    JointCount { expected: usize, actual: usize },
    #[error("invalid transition from {0:?}")]
    Invalid(GraspState),
}
pub struct GraspMachine {
    profile: Profile,
    state: GraspState,
}
impl GraspMachine {
    pub fn new(profile: Profile) -> Self {
        Self {
            profile,
            state: GraspState::Idle,
        }
    }
    pub fn profile(&self) -> &Profile {
        &self.profile
    }
    pub fn state(&self) -> &GraspState {
        &self.state
    }
    pub fn calibrate(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Idle {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Calibrating;
        Ok(())
    }
    pub fn calibration_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Calibrating {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Ready;
        Ok(())
    }
    pub fn grasp(&mut self, joints: &[f64]) -> Result<(), GraspError> {
        if joints.len() != self.profile.joint_count() {
            return Err(GraspError::JointCount {
                expected: self.profile.joint_count(),
                actual: joints.len(),
            });
        }
        if self.state != GraspState::Ready {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Grasping;
        Ok(())
    }
    pub fn grasp_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Grasping {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Holding;
        Ok(())
    }
    pub fn release(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Holding {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Releasing;
        Ok(())
    }
    pub fn release_complete(&mut self) -> Result<(), GraspError> {
        if self.state != GraspState::Releasing {
            return Err(GraspError::Invalid(self.state.clone()));
        }
        self.state = GraspState::Ready;
        Ok(())
    }
    pub fn abort(&mut self) {
        self.state = GraspState::Aborted
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_profiles_and_abort() {
        for p in [
            Profile::O6,
            Profile::L6,
            Profile::L7,
            Profile::L10,
            Profile::L20,
        ] {
            let n = p.joint_count();
            let mut g = GraspMachine::new(p);
            g.calibrate().unwrap();
            g.calibration_complete().unwrap();
            assert!(g.grasp(&vec![0.; n]).is_ok());
            g.grasp_complete().unwrap();
            g.release().unwrap();
            g.release_complete().unwrap();
            g.abort();
            assert_eq!(*g.state(), GraspState::Aborted);
        }
    }
}
