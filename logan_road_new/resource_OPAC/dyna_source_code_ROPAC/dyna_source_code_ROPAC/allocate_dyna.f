      subroutine  allocate_dyna

      use muc_mod

   	integer error


	if(iteration.eq.0)then

	allocate (NoofGenLinksPerZone(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate NoofGenLinksPerZone error'
	  stop
	endif
	NoofGenLinksPerZone(:)=0

	endif

	allocate (zdem(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zdem error - insufficient memory'
	  stop
	endif
	zdem(:,:)=0

	allocate (zfdem(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zfdem error - insufficient memory'
	  stop
	endif
	zfdem(:,:)=0

	allocate (zfdemT(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zfdemT error-insufficient memory'
	  stop
	endif
	zfdemT(:,:)=0

	allocate (zfdemH(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zfdemH error - insufficient memory'
	  stop
	endif
	zfdemH(:,:)=0

	allocate (ztdemGen(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ztdemGen error - insufficient memory'
	  stop
	endif
	ztdemGen(:)=0

	allocate (ztdemGenT(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ztdemGenT error - insufficient memory'
	  stop
	ztdemGenT(:)=0
	endif

	allocate (expgenzT(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate expgenzT error - insufficient memory'
	  stop
	endif
	expgenzT(:)=0
      
	allocate (zdemT(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zdemT error - insufficient memory'
	  stop
	endif
	zdemT(:,:)=0
      
	allocate (ztdemGenH(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ztdemGenH error - insufficient memory'
	  stop
	ztdemGenH(:)=0
	endif

	allocate (expgenzH(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate expgenzH error - insufficient memory'
	  stop
	endif
	expgenzH(:)=0

	allocate (zdemH(nzones,nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate zdemH error - insufficient memory'
	  stop
	endif
	zdemH(:,:)=0

	allocate (ztdemAtt(nzones,nints),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate ztdemAtt error - insufficient memory'
	  stop
	endif
	ztdemAtt(:,:)=0

	allocate (TotalLinkLenPerZone(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate totlmz error - insufficient memory'
	  stop
	endif
	TotalLinkLenPerZone(:)=0

	allocate (expgenz(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate expgenz error - insufficient memory'
	  stop
	endif
	expgenz(:)=0


      if(vms_num.gt.0)then

      allocate(vmstypetwopath(vms_num,100),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate vmstypetwopath error-insufficient memory'
	  stop
	endif
	vmstypetwopath(:,:)%node = 0 
	vmstypetwopath(:,:)%link = 0

      allocate(vmstype(vms_num),stat=error)
	if(error.ne.0) then 
	  write(911,*) 'allocate vmstype error - insufficient memory'
	  stop
	endif
	vmstype(:) = 0 
	
      allocate(vms(vms_num,4),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vms error - insufficient memory'
	  stop
	endif
	vms(:,:) = 0
	
      allocate(vms_start(vms_num),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vms_start error-insufficient memory'
	  stop
	endif
	vms_start(:) = 0
	
      allocate(vms_end(vms_num),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vms_end error - insufficient memory'
	  stop
	endif
	vms_end(:) = 0
      
	else

      allocate(vmstypetwopath(1,1),stat=error)
	if(error.ne.0) then 
      write(911,*)'allocate vmstypetwopath error-insufficient memory'
	  stop
	endif
	vmstypetwopath(:,:)%node = 0 
	vmstypetwopath(:,:)%link = 0

      allocate(vmstype(1),stat=error)
 	if(error.ne.0) then
	  write(911,*) 'allocate vmstype error- insufficient memory'
	  stop
	endif
	vmstype(:) = 0 
	
      allocate(vms(1,4),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate vms error - insufficient memory'
	  stop
	endif
	vms(:,:) = 0
	
      allocate(vms_start(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vms_start error-insufficient memory'
	  stop
	endif
	vms_start(:) = 0
	
      allocate(vms_end(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate vms_end error-insufficient memory'
	  stop
	endif
	vms_end(:) = 0

	endif


	if(dec_num.gt.0) then

	allocate(ramp_par(dec_num,3),stat=error)
	if(error.ne.0) then
       write(911,*)'allocate ramp_par error-insufficient memory'
	  stop
	endif
	ramp_par(:,:)=0.0
	
      allocate(ramp_start(dec_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ramp_start error-insufficient memory'
	  stop
	endif
	ramp_start(:)=0.0
	
      allocate(ramp_end(dec_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ramp_end error-insufficient memory'
	  stop
	endif
	ramp_end(:)=0.0
	
      allocate(detector(dec_num,7),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate detector error-insufficient memory'
	  stop
	endif
	detector(:,:)=0

      allocate(detector_length(dec_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate detector error-insufficient memory'
	  stop
	endif
	detector_length(:)=0
	
      allocate(detector_ramp(dec_num),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate detector_ramp error - 
     +  insufficient memory'
	  stop
	endif
      detector_ramp(:)=0
     	
	allocate(det_link(dec_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate det_link error-insufficient memory'
	  stop
	endif
	det_link(:)=0
	
      allocate(occup(dec_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate occup error-insufficient memory'
	  stop
	endif
	occup(:)=0
      
	else
	
      allocate(ramp_par(1,3),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ramp_par error-insufficient memory'
	  stop
	endif
	ramp_par(:,:) = 0
	
      allocate(ramp_start(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ramp_start error-insufficient memory'
	  stop
	endif
	ramp_start(:)=0.0

	allocate(ramp_end(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate ramp_end error-insufficient memory'
	  stop
	endif
	ramp_end(:)=0.0
	
      allocate(detector(1,7),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate detector error-insufficient memory'
	  stop
	endif
	detector(:,:)=0
	
      allocate(detector_length(1),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate detector_length error - 
     + insufficient memory'
	  stop
	endif
	detector_length(:)=0
	
      allocate(detector_ramp(1),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate detector_ramp error - 
     +  insufficient memory'
	  stop
	endif
      detector_ramp(:)=0
     	
	allocate(det_link(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate det_link error-insufficient memory'
	  stop
	endif
	det_link(:)=0
	
      allocate(occup(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate occup error-insufficient memory'
	  stop
	endif
	occup(:)=0
	
      endif

	if(inci_num.gt.0) then

     	allocate(incistartflag(inci_num),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate incistartflag error - 
     +  insufficient memory'
	  stop
	endif
 	incistartflag(:) = .False.
      
      allocate(inci(inci_num,3),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate inci error-insufficient memory'
	  stop
	endif
	inci(:,:)=0
	
      allocate(incil(inci_num),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate incil error-insufficient memory'
	  stop
	endif
	incil(:)=0
	
      allocate(incilist(inci_num),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate incilist error-insufficient memory'
	  stop
	endif
	incilist(:)=0
	
      allocate(itp(inci_num),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate itp error-insufficient memory'
	  stop
	endif
	itp(:)=0
	
      else

	allocate(incistartflag(1),stat=error)
	if(error.ne.0) then
	  write(911,*) 'allocate incistartflag error - 
     +  insufficient memory'
	  stop
	endif
 	incistartflag(:) = .False.
      
	allocate(inci(1,3),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate inci error-insufficient memory'
	  stop
	endif
	inci(:,:)=0
	
      allocate(incil(1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate incil error-insufficient memory'
	  stop
	endif
	incil(:)=0
	
      allocate(incilist(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate incilist error-insufficient memory'
	  stop
	endif
	incilist(:)=0
	
      allocate(itp(1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate itp error-insufficient memory'
	  stop
	endif
	itp(:)=0
 	
      endif


      if(WorkZoneNum.gt.0) then
      allocate(WorkZone(WorkZoneNum),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate WorkZone error-insufficient memory'
	  stop
	endif
      WorkZone(:)%FNode=0
	WorkZone(:)%TNode=0
      WorkZone(:)%ST=0          ! starting time
	WorkZone(:)%ET=0          ! ending time
	WorkZone(:)%CapRed=0      ! percentage of capacity reduction
      WorkZone(:)%SpeedLmt=0    ! speed limit in work zone
	WorkZone(:)%Discharge=0   ! discharge rate at work zone
	WorkZone(:)%OrigDisChg=0

      allocate (wzstartflag(WorkZoneNum),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate wzstartflag error-insufficient memory'
	  stop
	endif
	wzstartflag(:)=.False.

      else

      allocate(WorkZone(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate WorkZone error-insufficient memory'
	  stop
	endif
      WorkZone(:)%FNode=0
	WorkZone(:)%TNode=0
      WorkZone(:)%ST=0          ! starting time
	WorkZone(:)%ET=0          ! ending time
	WorkZone(:)%CapRed=0      ! percentage of capacity reduction
      WorkZone(:)%SpeedLmt=0    ! speed limit in work zone
	WorkZone(:)%Discharge=0   ! discharge rate at work zone
	WorkZone(:)%OrigDisChg=0

      allocate (wzstartflag(1),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate wzstartflag error-insufficient memory'
	  stop
	endif
	wzstartflag(:)=.False.

	endif
c ----
c ---- The following arrays are allocated only at the initial iteration
c ----
      if(iteration.eq.0) then

      allocate (destination(noof_master_destinations),stat=error)
	if(error.ne.0) then
      write(911,*)'allocate destination error-insufficient memory'
	  stop
	endif
      destination(:)=0

      allocate (origin(nzones),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate origin error-insufficient memory'
	  stop
	endif
      origin(:)=0

      allocate (MasterDest(nzones),stat=error)
 	if(error.ne.0) then
      write(911,*)'allocate destination error-insufficient memory'
	  stop
	endif
      MasterDest(:)=0

      endif
c ----------------------------------------------------

	allocate(begint(nints+1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate begint error-insufficient memory'
	  stop
	endif
	begint(:) = 0

	allocate(begintT(nints+1),stat=error)
	if(error.ne.0) then
	  write(911,*)'allocate begintT error-insufficient memory'
	  stop
	endif
	begintT(:) = 0

 
	  allocate(begintH(nints+1),stat=error)
	  if(error.ne.0) then
	  write(911,*)'allocate begintH error-insufficient memory'
	  stop
	  endif
	  begintH(:) = 0

      allocate(strtsig(isig+1),stat=error)
	  if(error.ne.0) then
      write(911,*)'allocate strtsig error-insufficient memory'
	  stop
	  endif
	  strtsig(:) = 0
      
	  allocate(decisionnum(nu_switch+1),stat=error)
	  if(error.ne.0) then
      write(911,*)'allcoate decisionum error-insufficient memory'
	  stop
	  endif
	  decisionnum(:) = 0
	
      allocate(switchnum(nu_switch+1),stat=error)
	  if(error.ne.0) then
      write(911,*)'allocate switchnum error-insufficient memory'
	  stop
	  endif
	  switchnum(:) = 0

	  if(iteration.eq.0) then

	  allocate (LinkNoInZone(nzones,1000),stat=error)
	  if(error.ne.0) then 
       write(911,*)'allocate LinkNoInZone error-insufficient memory'
	  stop
	  endif
	  LinkNoInZone(:,:)=0

	  endif

	  allocate (NoofConsPerZone(nzones),stat=error)
	  if(error.ne.0) then 
       write(911,*)'allocate NoofConsPerZone error-insufficient memory'
	  stop
	  endif
	  NoofConsPerZone(:)=0

	  allocate (ConNoInZone(nzones,1000),stat=error)
	  if(error.ne.0) then 
       write(911,*)'allocate ConNoInZone error-insufficient memory'
	  stop
	  endif
	  ConNoInZone(:,:)=0

      allocate (GradeBPnt(GradeNum),stat=error)
	  if(error.ne.0) then 
      write(911,*)'allocate GradeBPnt error-insufficient memory'
	  stop
	  endif
      GradeBPnt(:)=0

      allocate (LengthBPnt(GradeNum,LenNum),stat=error)
	  if(error.ne.0) then 
      write(911,*)'allocate LengthBPnt error-insufficient memory'
	  stop
	  endif
      LengthBPnt(:,:)=0

	  allocate (TruckBPnt(TruckNum),stat=error)
	  if(error.ne.0) then 
      write(911,*)'allocate TruckBPnt error-insufficient memory'
	  stop
	  endif
      TruckBPnt(:)=0

      allocate (PCE(GradeNum,LenNum,TruckNum),stat=error)      
	  if(error.ne.0) then 
      write(911,*)'allocate PCE error-insufficient memory'
	  stop
	  endif
      PCE(:,:,:)=0

      return
      end
